import QtQuick
import org.qfield
import org.qgis
import Theme

// QField app plugin that runs code sent by qfield-driver on localhost.
// Members are prefixed because a hosted plugin resolves unknown names through
// this file's context.
Item {
  id: qfieldDriver

  readonly property string _pqfEndpoint: "__ENDPOINT__"
  property bool _pqfBusy: false
  property var _pqfState: ({})
  property var _pqfHosted: null

  function _pqfFind(name) {
    return iface.findItemByObjectName(name);
  }

  function _pqfScene() {
    let item = iface.mainWindow().contentItem;
    while (item.parent) {
      item = item.parent;
    }
    return item;
  }

  // Depth first search over visual children, hidden ones included.
  function _pqfWalk(item, test, depth) {
    if (!item || (depth || 0) > 60) {
      return null;
    }
    if (test(item)) {
      return item;
    }
    const kids = item.children || [];
    for (let i = 0; i < kids.length; i++) {
      const hit = _pqfWalk(kids[i], test, (depth || 0) + 1);
      if (hit) {
        return hit;
      }
    }
    return null;
  }

  function _pqfWalkAll(item, test, depth, found) {
    const hits = found || [];
    if (!item || (depth || 0) > 60) {
      return hits;
    }
    if (test(item)) {
      hits.push(item);
    }
    const kids = item.children || [];
    for (let i = 0; i < kids.length; i++) {
      _pqfWalkAll(kids[i], test, (depth || 0) + 1, hits);
    }
    return hits;
  }

  // First item with an object name, in the scene and in the hosted plugin.
  function _pqfFindItem(name) {
    const test = i => i.objectName === name;
    return _pqfWalk(_pqfScene(), test, 0) || _pqfWalk(_pqfHosted, test, 0) || _pqfFind(name);
  }

  function _pqfHost(path) {
    if (_pqfHosted) {
      _pqfHosted.destroy();
      _pqfHosted = null;
    }
    const component = Qt.createComponent("file://" + path + "?t=" + Date.now());
    if (component.status !== Component.Ready) {
      throw new Error(component.errorString());
    }
    _pqfHosted = component.createObject(null);
    if (!_pqfHosted) {
      throw new Error(component.errorString());
    }
    return true;
  }

  function _pqfEncode(value) {
    if (value === undefined || value === null) {
      return null;
    }
    const kind = typeof value;
    if (kind === "number" || kind === "boolean" || kind === "string") {
      return value;
    }
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      return String(value);
    }
  }

  function _pqfSend(id, ok, value) {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", _pqfEndpoint + "/result");
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.send(JSON.stringify({
      "id": id,
      "ok": ok,
      "value": value
    }));
  }

  function _pqfRun(command) {
    try {
      const fn = new Function("iface", "find", "findItem", "walk", "walkAll", "scene", "state", "plugin", "driver", "qgisProject", "layerObserver", "pluginManager", "settings", "platformUtilities", "messageLogModel", "featureHistory", "flatLayerTree", "trackingModel", "LayerUtils", "GeometryUtils", "FeatureUtils", "StringUtils", "Theme", command.code);
      const value = fn(iface, _pqfFind, _pqfFindItem, _pqfWalk, _pqfWalkAll, _pqfScene, _pqfState, _pqfHosted, qfieldDriver, qgisProject, layerObserver, pluginManager, settings, platformUtilities, messageLogModel, featureHistory, flatLayerTree, trackingModel, LayerUtils, GeometryUtils, FeatureUtils, StringUtils, Theme);
      _pqfSend(command.id, true, _pqfEncode(value));
    } catch (error) {
      _pqfSend(command.id, false, String(error) + (error && error.stack ? "\n" + error.stack : ""));
    }
  }

  function _pqfPoll() {
    if (_pqfBusy) {
      return;
    }
    _pqfBusy = true;
    const xhr = new XMLHttpRequest();
    xhr.onreadystatechange = () => {
      if (xhr.readyState !== XMLHttpRequest.DONE) {
        return;
      }
      _pqfBusy = false;
      if (xhr.status === 200 && xhr.responseText) {
        _pqfRun(JSON.parse(xhr.responseText));
      }
    };
    xhr.open("GET", _pqfEndpoint + "/next");
    xhr.send();
  }

  Timer {
    interval: 20
    repeat: true
    running: true
    onTriggered: qfieldDriver._pqfPoll()
  }
}
