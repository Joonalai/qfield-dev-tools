import QtQuick
import QtQuick.Controls

// QField's main menu (qgismobileapp.qml) without the actions behind its
// items. A plain Menu, as QfMenu needs QField's mainWindow id. The first row
// holds undo and redo like QField's, the sensors item stays hidden without
// sensors. QField's icons aren't bundled, so the items keep icon.source for
// plugins to read but show text only, which loads no icon.
Menu {
    id: mainMenu

    objectName: "mainMenu"
    title: qsTr("Main Menu")

    Item {
        width: mainMenu.width
        height: 48

        MenuItem {
            text: qsTr("Undo")
            font: Theme.defaultFont
            display: AbstractButton.TextOnly
            icon.source: Theme.getThemeVectorIcon("ic_undo_black_24dp")
            width: parent.width / 2
            height: 48
            leftPadding: Theme.menuItemLeftPadding
        }

        MenuItem {
            text: qsTr("Redo")
            font: Theme.defaultFont
            display: AbstractButton.TextOnly
            icon.source: Theme.getThemeVectorIcon("ic_redo_black_24dp")
            x: parent.width / 2
            width: parent.width / 2
            height: 48
            leftPadding: Theme.menuItemLeftPadding
        }
    }

    MenuSeparator {
        width: parent.width
    }

    MenuItem {
        text: qsTr("Sensors")
        font: Theme.defaultFont
        display: AbstractButton.TextOnly
        icon.source: Theme.getThemeVectorIcon("ic_sensor_on_black_24dp")
        height: visible ? 48 : 0
        visible: false
        leftPadding: Theme.menuItemLeftPadding
    }

    MenuSeparator {
        width: parent.width
        visible: false
        height: visible ? undefined : 0
    }

    MenuItem {
        text: qsTr("Plugin Manager")
        font: Theme.defaultFont
        display: AbstractButton.TextOnly
        icon.source: Theme.getThemeVectorIcon("ic_plugin_black_24dp")
        height: 48
        leftPadding: Theme.menuItemLeftPadding
    }

    MenuItem {
        text: qsTr("Settings")
        font: Theme.defaultFont
        display: AbstractButton.TextOnly
        icon.source: Theme.getThemeVectorIcon("ic_tune_white_24dp")
        height: 48
        leftPadding: Theme.menuItemLeftPadding
    }

    MenuItem {
        text: qsTr("Message Log")
        font: Theme.defaultFont
        display: AbstractButton.TextOnly
        icon.source: Theme.getThemeVectorIcon("ic_message_log_black_24dp")
        height: 48
        leftPadding: Theme.menuItemLeftPadding
    }

    MenuItem {
        text: qsTr("Lock Screen")
        font: Theme.defaultFont
        display: AbstractButton.TextOnly
        icon.source: Theme.getThemeVectorIcon("ic_lock_black_24dp")
        height: 48
        leftPadding: Theme.menuItemLeftPadding
    }

    MenuSeparator {
        width: parent.width
    }

    MenuItem {
        text: qsTr("About QField")
        font: Theme.defaultFont
        display: AbstractButton.TextOnly
        icon.source: Theme.getThemeVectorIcon("ic_qfield_black_24dp")
        height: 48
        leftPadding: Theme.menuItemLeftPadding
    }
}
