"""Method table for the RemoteFortressReader plugin (DFHack 0.47.05-r5).

Each entry maps an RFR method name to the fully-qualified protobuf type
names BindMethod needs plus the generated message classes, so callers can
do ``client.call("GetVersionInfo", EmptyMessage())`` without spelling out
the wire details.

Source of the method list: ``plugins/proto/RemoteFortressReader.proto``
at tag 0.47.05-r5 (the ``// RPC ...`` comments at the top of the file).
Only methods whose input/output types exist in the vendored stubs are
listed; the table grows as later phases need more. Anything not listed
here can still be called via :meth:`DFHackClient.call` with explicit
type names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from google.protobuf.message import Message

from .proto import CoreProtocol_pb2 as core
from .proto import RemoteFortressReader_pb2 as rfr

PLUGIN = "RemoteFortressReader"


@dataclass(frozen=True)
class MethodSpec:
    """One bindable RPC method."""

    plugin: str
    input_msg: str  # fully-qualified protobuf type name, for BindMethod
    output_msg: str
    input_cls: Type[Message]
    output_cls: Type[Message]


def _spec(input_msg: str, output_msg: str,
          input_cls: Type[Message], output_cls: Type[Message]) -> MethodSpec:
    return MethodSpec(PLUGIN, input_msg, output_msg, input_cls, output_cls)


_EMPTY = "dfproto.EmptyMessage"
_RFR = "RemoteFortressReader."

#: RemoteFortressReader methods (subset used by the harness so far).
METHODS: dict[str, MethodSpec] = {
    "GetVersionInfo": _spec(_EMPTY, _RFR + "VersionInfo",
                            core.EmptyMessage, rfr.VersionInfo),
    "GetPauseState": _spec(_EMPTY, _RFR + "SingleBool",
                           core.EmptyMessage, rfr.SingleBool),
    "SetPauseState": _spec(_RFR + "SingleBool", _EMPTY,
                           rfr.SingleBool, core.EmptyMessage),
    "GetMapInfo": _spec(_EMPTY, _RFR + "MapInfo",
                        core.EmptyMessage, rfr.MapInfo),
    "GetViewInfo": _spec(_EMPTY, _RFR + "ViewInfo",
                         core.EmptyMessage, rfr.ViewInfo),
    "GetUnitList": _spec(_EMPTY, _RFR + "UnitList",
                         core.EmptyMessage, rfr.UnitList),
    "GetUnitListInside": _spec(_RFR + "BlockRequest", _RFR + "UnitList",
                               rfr.BlockRequest, rfr.UnitList),
    "GetBlockList": _spec(_RFR + "BlockRequest", _RFR + "BlockList",
                          rfr.BlockRequest, rfr.BlockList),
    "GetTiletypeList": _spec(_EMPTY, _RFR + "TiletypeList",
                             core.EmptyMessage, rfr.TiletypeList),
    "GetPlantList": _spec(_RFR + "BlockRequest", _RFR + "PlantList",
                          rfr.BlockRequest, rfr.PlantList),
    "GetBuildingDefList": _spec(_EMPTY, _RFR + "BuildingList",
                                core.EmptyMessage, rfr.BuildingList),
    "GetReports": _spec(_EMPTY, _RFR + "Status",
                        core.EmptyMessage, rfr.Status),
    "GetGameValidity": _spec(_EMPTY, _RFR + "SingleBool",
                             core.EmptyMessage, rfr.SingleBool),
    "CopyScreen": _spec(_EMPTY, _RFR + "ScreenCapture",
                        core.EmptyMessage, rfr.ScreenCapture),
    "PassKeyboardEvent": _spec(_RFR + "KeyboardEvent", _EMPTY,
                               rfr.KeyboardEvent, core.EmptyMessage),
    "SendDigCommand": _spec(_RFR + "DigCommand", _EMPTY,
                            rfr.DigCommand, core.EmptyMessage),
}
