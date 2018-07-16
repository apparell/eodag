# -*- coding: utf-8 -*-
# Copyright 2018, CS Systemes d'Information, http://www.c-s.fr
#
# This file is part of EODAG project
#     https://www.github.com/CS-SI/EODAG
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import absolute_import, print_function, unicode_literals

import logging
import re

import pyproj
from owslib.csw import CatalogueServiceWeb
from owslib.fes import (
    BBox, PropertyIsEqualTo, PropertyIsGreaterThanOrEqualTo, PropertyIsLessThanOrEqualTo, PropertyIsLike,
)
from owslib.ows import ExceptionReport
from shapely import geometry

from eodag.api.product import EOProduct
from eodag.api.product.representations import properties_from_xml
from eodag.plugins.search.base import Search
from eodag.utils import DEFAULT_PROJ, slugify
from eodag.utils.import_system import patch_owslib_requests


logger = logging.getLogger('beodag.plugins.search.csw')

SUPPORTED_REFERENCE_SCHEMES = [
    'WWW:DOWNLOAD-1.0-http--download',
]

# Configuration keys
SEARCH_DEF = 'search_definitions'
PRODUCT_TYPE = 'pt_tags'
DATE = 'date_tags'


class CSWSearch(Search):

    def __init__(self, config):
        super(CSWSearch, self).__init__(config)
        self.catalog = None

    def query(self, product_type, **kwargs):
        logger.info('New search for product type : %s on %s interface', product_type, self.name)
        auth = kwargs.pop('auth', None)
        if auth is not None:
            self.__init_catalog(**auth.config['credentials'])
        else:
            self.__init_catalog()
        results = []
        if self.catalog:
            for product_type_def in self.config[SEARCH_DEF][PRODUCT_TYPE]:
                product_type_search_tag = product_type_def['name']
                logger.debug('Querying %s for product type %s', product_type_search_tag, product_type)
                constraints = self.__convert_query_params(product_type_def, product_type, kwargs)
                with patch_owslib_requests(verify=False):
                    try:
                        self.catalog.getrecords2(constraints=constraints, esn='full', maxrecords=10)
                    except ExceptionReport:
                        import traceback as tb
                        logger.warning('Failed to query %s for product type %s : %s', product_type_search_tag,
                                       product_type, tb.format_exc())
                        continue
                partial_results = [
                    self.__build_product(record, product_type, **kwargs) for record in self.catalog.records.values()]
                logger.info('Found %s results querying %s', len(partial_results), product_type_search_tag)
                results.extend(partial_results)
        logger.info('Found %s overall results', len(results))
        return results

    def __init_catalog(self, username=None, password=None):
        """Initializes a catalogue by performing a GetCapabilities request on the url"""
        if not self.catalog:
            logger.debug('Initialising CSW catalog at %s', self.config['api_endpoint'])
            with patch_owslib_requests(verify=False):
                try:
                    self.catalog = CatalogueServiceWeb(
                        self.config['api_endpoint'],
                        version=self.config.get('version', '2.0.2'),
                        username=username,
                        password=password
                    )
                except Exception as e:
                    logger.warning('Initialization of catalog failed due to error: (%s: %s)', type(e), e)

    def __build_product(self, rec, product_type, **kwargs):
        """Enable search results to be handled by http download plugin"""
        bbox = rec.bbox_wgs84
        if not bbox:
            code = 'EPSG:4326'
            if rec.bbox.crs.code and rec.bbox.crs.code > 0:
                code = ':'.join((str(rec.bbox.crs.id), str(rec.bbox.crs.code)))
            rec_proj = pyproj.Proj(init=code)
            maxx, maxy = pyproj.transform(rec_proj, DEFAULT_PROJ, rec.bbox.maxx, rec.bbox.maxy)
            minx, miny = pyproj.transform(rec_proj, DEFAULT_PROJ, rec.bbox.minx, rec.bbox.miny)
            bbox = (minx, miny, maxx, maxy)
        download_url = ''
        resource_filter = re.compile(self.config[SEARCH_DEF].get('resource_location_filter', ''))
        for ref in rec.references:
            if ref['scheme'] in SUPPORTED_REFERENCE_SCHEMES:
                if resource_filter.pattern and resource_filter.search(ref['url']):
                    download_url = ref['url']
                else:
                    download_url = ref['url']
                break
        properties = properties_from_xml(rec.xml, self.config['metadata_mapping'])
        properties['title'] = slugify(rec.identifier)
        properties['geometry'] = geometry.box(*bbox)
        properties['productType'] = product_type
        return EOProduct(
            product_type,
            self.instance_name,
            download_url,
            properties,
            searched_bbox=kwargs.get('footprints'),
        )

    def __convert_query_params(self, product_type_def, product_type, params):
        """Translates eodag search to CSW constraints using owslib constraint classes"""
        constraints = []
        # How the match should be performed (fuzzy, prefix, postfix or exact). defaults to fuzzy
        pt_tag, matching = product_type_def['name'], product_type_def.get('matching', 'fuzzy')
        if matching == 'prefix':
            constraints.append(PropertyIsLike(pt_tag, '{}%'.format(product_type)))
        elif matching == 'postfix':
            constraints.append(PropertyIsLike(pt_tag, '%{}'.format(product_type)))
        elif matching == 'exact':
            constraints.append(PropertyIsEqualTo(pt_tag, product_type))
        else:  # unknown matching is considered to be equal to 'fuzzy'
            constraints.append(PropertyIsLike(pt_tag, '%{}%'.format(product_type)))

        # footprint
        fp = params.get('geometry')
        if fp:
            constraints.append(BBox([fp['lonmin'], fp['latmin'], fp['lonmax'], fp['latmax']]))

        # dates
        start, end = params.get('startTimeFromAscendingNode'), params.get('completionTimeFromAscendingNode')
        if start:
            constraints.append(PropertyIsGreaterThanOrEqualTo(self.config[SEARCH_DEF][DATE]['start'], start))
        if end:
            constraints.append(PropertyIsLessThanOrEqualTo(self.config[SEARCH_DEF][DATE]['end'], end))
        return [constraints] if len(constraints) > 1 else constraints