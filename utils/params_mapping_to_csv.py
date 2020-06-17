# -*- coding: utf-8 -*-
# Copyright 2020, CS GROUP - France, http://www.c-s.fr
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
from __future__ import absolute_import, unicode_literals

import csv
import logging
import os
import sys

import requests
from lxml import html

from eodag.api.core import EODataAccessGateway

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

OPENSEARCH_DOC_URL = "http://docs.opengeospatial.org/is/13-026r8/13-026r8.html"
DEFAULT_CSV_FILE_PATH = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "../docs/_static/params_mapping.csv"
)


def params_mapping_to_csv(
    ogc_doc_url=OPENSEARCH_DOC_URL, csv_file_path=DEFAULT_CSV_FILE_PATH
):
    """Get providers metadata mapping, with corresponding description from OGC
        documentation and writes it to a csv file

        :param ogc_doc_url: (Optional) URL to OGC OpenSearch documentation
        :type ogc_doc_url: str
        :param csv_file_path: (Optional) path to csv output file
        :type csv_file_path: str
    """
    dag = EODataAccessGateway()

    page = requests.get(ogc_doc_url)
    tree = html.fromstring(page.content.decode("utf8"))

    # list of lists of all parameters per provider
    params_list_of_lists = [
        list(dag.providers_config[p].search.__dict__["metadata_mapping"].keys())
        for p in dag.providers_config.keys()
        if hasattr(dag.providers_config[p], "search")
    ]

    # union of params_list_of_lists
    global_keys = sorted(list(set().union(*(params_list_of_lists))))

    # csv fieldnames
    fieldnames = ["param", "open-search", "class", "description", "type"] + sorted(
        [provider + "_mapping" for provider in dag.providers_config.keys()]
        + [provider + "_query" for provider in dag.providers_config.keys()]
    )
    # py2 compatibility
    if sys.version_info[0] < 3:
        fieldnames = [x.encode("utf8") for x in fieldnames]

    # write to csv
    with open(csv_file_path, "w") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for param in global_keys:
            params_row = {
                "param": param,
                "open-search": "",
                "class": "",
                "description": "",
                "type": "",
            }
            # search html node matching containing param
            param_node_list = tree.xpath(
                '/html/body/main/section/table/tr/td[1]/p[text()="%s"]' % param
            )

            for param_node in param_node_list:
                params_row["open-search"] = "yes"

                # table must have 3 columns, and 'Definition' as 2nd header
                if (
                    len(param_node.xpath("../../../thead/tr/th")) == 3
                    and "Definition"
                    in param_node.xpath("../../../thead/tr/th[2]/text()")[0]
                ):

                    params_row["class"] = param_node.xpath("../../../caption/text()")[
                        1
                    ].strip(": ")

                    # description formatting
                    params_row["description"] = param_node.xpath(
                        "../../td[2]/p/text()"
                    )[0].replace("\n", " ")
                    # multiple spaces to 1
                    params_row["description"] = " ".join(
                        params_row["description"].split()
                    )

                    params_row["type"] = param_node.xpath("../../td[3]/p/text()")[0]
                    break

            # write metadata mapping
            for provider in dag.providers_config.keys():
                if hasattr(dag.providers_config[provider], "search"):
                    mapping_dict = dag.providers_config[provider].search.__dict__[
                        "metadata_mapping"
                    ]
                    if param in mapping_dict.keys():
                        if isinstance(mapping_dict[param], list):
                            params_row[provider + "_query"] = mapping_dict[param][0]
                            params_row[provider + "_mapping"] = mapping_dict[param][1]
                        else:
                            params_row[provider + "_mapping"] = mapping_dict[param]

            # py2 compatibility
            if sys.version_info[0] < 3:
                params_row = {
                    k.encode("utf8"): v.encode("utf8") for k, v in params_row.items()
                }
            writer.writerow(params_row)

    logger.info(csv_file_path + " written")


if __name__ == "__main__":
    params_mapping_to_csv()
