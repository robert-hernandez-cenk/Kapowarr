# -*- coding: utf-8 -*-

from backend.base.definitions import DownloadType
from backend.implementations.query_builder_manager import QueryBuilders
from backend.implementations.query_builders.DDL import DDLQueryBuilder


@QueryBuilders.register_builder(DownloadType.USENET)
class UsenetQueryBuilder(DDLQueryBuilder):
    """
    Newznab search is keyword based, just like the GetComics search, so the
    same query formats and variations are used.
    """
