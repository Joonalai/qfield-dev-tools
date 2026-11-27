# Copyright (C) 2026 qfield-dev-tools Contributors.
#
#
# This file is part of qfield-dev-tools.
#
# qfield-dev-tools is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# qfield-dev-tools is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qfield-dev-tools.  If not, see <https://www.gnu.org/licenses/>.
"""Plugins that need an accurate fix read it from ``positionSource``.

These tests drive the pattern from QML: bind to
``positionInformation.hacc``, QField's name for the horizontal accuracy,
then cancel QField's move, rotate and
digitize tools when the fix is too inaccurate.
"""

import math
from typing import TYPE_CHECKING

import pytest

from pytest_qfield.stub_interface.qfield_stubs import (
    QFieldAccuracyQuality,
    QFieldFeatureListFormStub,
    QFieldGnssPositionInformationStub,
    QFieldPositioningSettingsStub,
    QFieldPositioningStub,
)

if TYPE_CHECKING:
    from pathlib import Path

    from PyQt6.QtCore import QObject

    from pytest_qfield.qfieldbot import QFieldBot


@pytest.fixture
def qfield_positioning_stub() -> QFieldPositioningStub:
    """Return a Positioning stub with a 2 m fix."""
    return QFieldPositioningStub(
        x=389870.0, y=6678167.0, horizontal_accuracy=2.0, vertical_accuracy=4.0
    )


@pytest.fixture
def accuracy_probe(qfield_bot: "QFieldBot", tmp_path: "Path") -> "QObject":
    probe_qml = tmp_path / "accuracy_probe.qml"
    probe_qml.write_text("""
import QtQuick

Item {
    readonly property var positionSource: iface.findItemByObjectName("positionSource")
    readonly property var settings: iface.findItemByObjectName("positioningSettings")
    readonly property var form: iface.findItemByObjectName("featureForm")

    readonly property real hacc: positionSource.positionInformation.hacc
    readonly property bool haccValid: positionSource.positionInformation.haccValid
    readonly property real vacc: positionSource.positionInformation.vacc
    readonly property int quality: positionSource.positionInformation.accuracyQuality
    readonly property real projectedHacc: positionSource.projectedHorizontalAccuracy
    readonly property bool accurate: haccValid && hacc <= settings.accuracyBad

    function cancelIfInaccurate(toolbar) {
        if (!accurate) {
            toolbar.cancel();
        }
    }

    Connections {
        target: form.moveFeaturesToolbar
        function onMoveFeaturesRequestedChanged() {
            if (form.moveFeaturesToolbar.moveFeaturesRequested) {
                cancelIfInaccurate(form.moveFeaturesToolbar);
            }
        }
    }

    Connections {
        target: form.rotateFeaturesToolbar
        function onRotateFeaturesRequestedChanged() {
            if (form.rotateFeaturesToolbar.rotateFeaturesRequested) {
                cancelIfInaccurate(form.rotateFeaturesToolbar);
            }
        }
    }

    property int moveConfirmations: 0
    property int digitizeConfirmations: 0

    Connections {
        target: form.moveFeaturesToolbar
        function onMoveConfirmed() {
            moveConfirmations += 1;
        }
    }

    Connections {
        target: form.digitizingToolbar
        function onConfirmed() {
            digitizeConfirmations += 1;
        }
    }

    function confirmTools() {
        form.moveFeaturesToolbar.confirm();
        form.digitizingToolbar.confirm();
    }

    Connections {
        target: form.digitizingToolbar
        function onGeometryRequestedChanged() {
            if (form.digitizingToolbar.geometryRequested) {
                cancelIfInaccurate(form.digitizingToolbar);
            }
        }
    }
}
""")
    return qfield_bot.load_qml(probe_qml)


def test_qml_reads_position_accuracy(accuracy_probe: "QObject") -> None:
    assert accuracy_probe.property("hacc") == 2.0
    assert accuracy_probe.property("haccValid") is True
    assert accuracy_probe.property("vacc") == 4.0
    assert accuracy_probe.property("quality") == QFieldAccuracyQuality.OK
    assert accuracy_probe.property("projectedHacc") == 2.0


def test_set_accuracy_updates_qml_bindings(
    accuracy_probe: "QObject", qfield_positioning_stub: QFieldPositioningStub
) -> None:
    qfield_positioning_stub.set_accuracy(0.5)
    assert accuracy_probe.property("hacc") == 0.5
    assert accuracy_probe.property("quality") == QFieldAccuracyQuality.EXCELLENT

    # None stands for a receiver that reports no accuracy.
    qfield_positioning_stub.set_accuracy(None)
    assert accuracy_probe.property("haccValid") is False
    assert math.isnan(accuracy_probe.property("hacc"))
    assert accuracy_probe.property("quality") == QFieldAccuracyQuality.BAD


@pytest.mark.usefixtures("accuracy_probe")
def test_accurate_fix_keeps_move_tool(
    qfield_feature_list_form_stub: QFieldFeatureListFormStub,
) -> None:
    toolbar = qfield_feature_list_form_stub.moveFeaturesToolbar
    toolbar.moveFeaturesRequested = True
    assert toolbar.moveFeaturesRequested is True


@pytest.mark.usefixtures("accuracy_probe")
@pytest.mark.parametrize(
    ("toolbar_name", "requested_name", "canceled_signal"),
    [
        ("moveFeaturesToolbar", "moveFeaturesRequested", "moveCanceled"),
        ("rotateFeaturesToolbar", "rotateFeaturesRequested", "rotateCanceled"),
        ("digitizingToolbar", "geometryRequested", None),
    ],
)
def test_inaccurate_fix_cancels_form_tools(
    qfield_positioning_stub: QFieldPositioningStub,
    qfield_feature_list_form_stub: QFieldFeatureListFormStub,
    toolbar_name: str,
    requested_name: str,
    canceled_signal: str | None,
) -> None:
    qfield_positioning_stub.set_accuracy(8.0)
    toolbar = getattr(qfield_feature_list_form_stub, toolbar_name)
    canceled: list[bool] = []
    toolbar.cancel.connect(lambda: canceled.append(True))
    if canceled_signal:
        getattr(toolbar, canceled_signal).connect(lambda: canceled.append(True))

    setattr(toolbar, requested_name, True)

    assert getattr(toolbar, requested_name) is False
    assert len(canceled) == (2 if canceled_signal else 1)


def test_plugin_threshold_can_come_from_positioning_settings(
    accuracy_probe: "QObject",
    qfield_positioning_settings_stub: QFieldPositioningSettingsStub,
) -> None:
    assert accuracy_probe.property("accurate") is True
    qfield_positioning_settings_stub.accuracyBad = 1.5  # type: ignore[method-assign]
    assert accuracy_probe.property("accurate") is False


def test_accuracy_quality_uses_thresholds() -> None:
    stub = QFieldPositioningStub(horizontal_accuracy=3.0)
    assert stub.positionInformation.accuracyQuality == QFieldAccuracyQuality.OK

    stub.badAccuracyThreshold = 2.0  # type: ignore[method-assign]
    assert stub.positionInformation.accuracyQuality == QFieldAccuracyQuality.BAD

    stub.excellentAccuracyThreshold = math.nan  # type: ignore[method-assign]
    assert stub.positionInformation.accuracyQuality == (
        QFieldAccuracyQuality.UNDETERMINED
    )


def test_default_positioning_stub_has_no_accuracy() -> None:
    information = QFieldPositioningStub().positionInformation
    assert isinstance(information, QFieldGnssPositionInformationStub)
    assert information.haccValid is False
    assert information.vaccValid is False
    assert math.isnan(QFieldPositioningStub().projectedHorizontalAccuracy)


def test_confirm_clears_requests_like_qfield(
    accuracy_probe: "QObject",
    qfield_bot: "QFieldBot",
    qfield_feature_list_form_stub: QFieldFeatureListFormStub,
) -> None:
    form = qfield_feature_list_form_stub
    form.moveFeaturesToolbar.moveFeaturesRequested = True
    form.digitizingToolbar.geometryRequested = True

    qfield_bot.call_qml(accuracy_probe, "confirmTools")

    assert form.moveFeaturesToolbar.moveFeaturesRequested is False
    assert form.digitizingToolbar.geometryRequested is False
    assert accuracy_probe.property("moveConfirmations") == 1
    assert accuracy_probe.property("digitizeConfirmations") == 1
