import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar button + duration menu. Picking a duration hands off to the service,
// which owns the session lock; this file never touches the lock itself.
Panel {
  id: root

  moduleName: "zds.blackwall"
  ipcTarget: "zds.blackwall.menu"

  // The service singleton, resolved through the shell. QML captures the
  // property reads inside serviceFor(), so this re-evaluates if services are
  // remounted (a plugin rescan, for instance).
  readonly property var service: bar && bar.shell && typeof bar.shell.serviceFor === "function"
    ? bar.shell.serviceFor("zds.blackwall")
    : null

  // "menu" -> presets, "custom" -> minutes field, "confirm" -> long-lock warning
  property string stage: "menu"
  property int customMinutes: 45
  property int pendingMinutes: 0
  property int cursorIndex: -1

  readonly property var presets: Model.PRESET_MINUTES

  // QQC.SpinBox only pushes typed text into `value` when the edit is
  // committed — Enter, or the field losing focus. Someone who types a number
  // and goes straight to Engage never commits, so `value` (and with it
  // customMinutes) would still hold the previous figure and the lock would
  // run for the wrong duration. Read the editor text directly instead.
  function enterCustomStage() {
    stage = "custom"
    // Focus after the stage switch has laid the field out.
    Qt.callLater(function() {
      if (root.stage === "custom" && minutesField.field) minutesField.field.forceActiveFocus()
    })
  }

  function commitMinutes() {
    var spin = minutesField.field
    var editor = spin ? spin.contentItem : null
    if (editor) {
      var typed = parseInt(String(editor.text).replace(/[^0-9]/g, ""), 10)
      if (isFinite(typed) && typed > 0)
        customMinutes = Math.round(Model.clamp(typed, 1, Math.floor(Model.MAX_SECONDS / 60)))
    }
    return customMinutes
  }

  function resetStage() {
    stage = "menu"
    pendingMinutes = 0
    cursorIndex = -1
  }

  // Presets, the Custom row, and the persistence toggle share one cursor
  // index space: 0..n-1 presets, then Custom, then the toggle.
  readonly property int menuItemCount: presets.length + 4
  readonly property int customIndex: presets.length
  readonly property int persistIndex: presets.length + 1
  readonly property int soundIndex: presets.length + 2
  readonly property int stationIndex: presets.length + 3

  readonly property bool persistAcrossReboot: service ? service.persistAcrossReboot === true : true
  readonly property bool soundEnabled: service ? service.soundEnabled === true : true

  // What the schedule is about to do, for the menu. Empty when nothing is
  // scheduled, so the row simply is not there rather than saying "off".
  readonly property string scheduleLine: {
    if (!root.service || root.service.scheduleEnabled !== true) return ""
    var a = root.service.activeWindow
    if (a) return a.label + " — " + a.endsInMinutes + " min left"
    var n = root.service.nextWindow
    if (!n) return ""
    if (n.inMinutes < 60) return n.label + " in " + n.inMinutes + " min"
    var h = Math.floor(n.inMinutes / 60)
    return n.label + " in " + h + "h " + (n.inMinutes % 60) + "m"
  }

  function toggleSound() {
    if (root.service) root.service.setSoundEnabled(!root.soundEnabled)
  }

  function togglePersist() {
    if (root.service && typeof root.service.setPersistAcrossReboot === "function")
      root.service.setPersistAcrossReboot(!root.persistAcrossReboot)
    else
      Quickshell.execDetached(["omarchy-shell", "blackwall", "setPersist",
                               root.persistAcrossReboot ? "false" : "true"])
  }

  // The station is a panel entry point on this same plugin, so the shell can
  // summon it directly. The detached command is the fallback for a bar that
  // was handed no shell reference -- the same shape every other action here
  // uses, and for the same reason.
  function openStation() {
    root.close()
    if (root.bar && root.bar.shell && typeof root.bar.shell.summon === "function")
      root.bar.shell.summon("zds.blackwall", "{}")
    else
      Quickshell.execDetached(["omarchy-shell", "shell", "summon",
                               "zds.blackwall", "{}"])
  }

  function moveCursor(delta) {
    if (stage !== "menu") return
    if (cursorIndex < 0) { cursorIndex = 0; return }
    cursorIndex = (cursorIndex + delta + menuItemCount) % menuItemCount
  }

  function activateCursor() {
    if (stage === "confirm") { commit(pendingMinutes); return }
    if (stage === "custom") { request(commitMinutes()); return }
    if (cursorIndex < 0) return
    if (cursorIndex < presets.length) request(presets[cursorIndex])
    else if (cursorIndex === customIndex) enterCustomStage()
    else if (cursorIndex === persistIndex) togglePersist()
    else if (cursorIndex === soundIndex) toggleSound()
    else if (cursorIndex === stationIndex) openStation()
  }

  // Everything routes through here so the long-lock warning cannot be
  // bypassed by a different entry point into the menu.
  function request(minutes) {
    var value = Math.round(Number(minutes))
    if (!isFinite(value) || value <= 0) return
    if (Model.needsWarning(value)) {
      pendingMinutes = value
      stage = "confirm"
      return
    }
    commit(value)
  }

  function commit(minutes) {
    var seconds = Model.secondsForMinutes(minutes)
    if (root.service && typeof root.service.engage === "function") root.service.engage(seconds)
    else Quickshell.execDetached(["omarchy-shell", "blackwall", "engage", String(seconds)])
    root.close()
  }

  onOpenedChanged: if (!opened) resetStage()

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    tooltipText: "Blackwall"
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(300))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: minutesField.field.activeFocus
      onMoveRequested: function(dx, dy) { root.moveCursor(dy !== 0 ? dy : dx) }
      onActivateRequested: root.activateCursor()
      onCloseRequested: {
        if (root.stage === "menu") root.close()
        else root.resetStage()
      }
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(12)

        // ------------------------------------------------------------ hero
        Column {
          width: parent.width
          spacing: Style.space(2)

          Text {
            text: "Blackwall"
            color: root.barForeground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }

          Text {
            text: "Locks the session. No way out until it lifts."
            color: Qt.darker(root.barForeground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
            width: parent.width
          }
        }

        PanelSeparator { foreground: root.barForeground }

        // --------------------------------------------------------- presets
        Column {
          visible: root.stage === "menu"
          width: parent.width
          spacing: Style.space(8)

          PanelSectionHeader {
            text: "LOCK FOR"
            foreground: root.barForeground
            fontFamily: root.bar.fontFamily
          }

          Grid {
            id: presetGrid
            width: parent.width
            columns: 2
            columnSpacing: Style.space(6)
            rowSpacing: Style.space(6)

            readonly property real cellWidth: (width - columnSpacing) / 2

            Repeater {
              model: root.presets

              Button {
                required property var modelData
                required property int index
                width: presetGrid.cellWidth
                text: Model.formatDuration(modelData)
                fontSize: Style.font.bodySmall
                foreground: root.barForeground
                fontFamily: root.bar.fontFamily
                bordered: true
                hasCursor: root.cursorIndex === index
                onClicked: root.request(modelData)
                onHovered: function(on) { if (on) root.cursorIndex = index }
              }
            }
          }

          Button {
            width: parent.width
            text: "Custom…"
            fontSize: Style.font.bodySmall
            foreground: root.barForeground
            fontFamily: root.bar.fontFamily
            bordered: true
            hasCursor: root.cursorIndex === root.customIndex
            onClicked: root.enterCustomStage()
            onHovered: function(on) { if (on) root.cursorIndex = root.customIndex }
          }

          PanelSeparator { foreground: root.barForeground }

          PanelSectionHeader {
            width: parent.width
            visible: root.scheduleLine !== ""
            text: "SCHEDULED  ·  " + root.scheduleLine
            foreground: root.barForeground
            fontFamily: root.bar.fontFamily
          }

          Toggle {
            width: parent.width
            label: "Sound"
            description: root.soundEnabled
              ? "The wall has a voice while it is up."
              : "Silent — the wall comes up without a sound."
            checked: root.soundEnabled
            hasCursor: root.cursorIndex === root.soundIndex
            foreground: root.barForeground
            fontFamily: root.bar.fontFamily
            onClicked: root.toggleSound()
            onHovered: function(on) { if (on) root.cursorIndex = root.soundIndex }
          }

          Toggle {
            width: parent.width
            label: "Persist Across Reboot"
            description: root.persistAcrossReboot
              ? "A lock survives a reboot and resumes."
              : "Session only — a reboot clears the lock."
            checked: root.persistAcrossReboot
            hasCursor: root.cursorIndex === root.persistIndex
            foreground: root.barForeground
            fontFamily: root.bar.fontFamily
            onClicked: root.togglePersist()
            onHovered: function(on) { if (on) root.cursorIndex = root.persistIndex }
          }

          PanelSeparator { foreground: root.barForeground }

          Button {
            width: parent.width
            text: "NetWatch Station…"
            fontSize: Style.font.bodySmall
            foreground: root.barForeground
            fontFamily: root.bar.fontFamily
            bordered: true
            hasCursor: root.cursorIndex === root.stationIndex
            onClicked: root.openStation()
            onHovered: function(on) { if (on) root.cursorIndex = root.stationIndex }
          }
        }

        // ---------------------------------------------------------- custom
        Column {
          visible: root.stage === "custom"
          width: parent.width
          spacing: Style.space(10)

          PanelSectionHeader {
            text: "CUSTOM DURATION"
            foreground: root.barForeground
            fontFamily: root.bar.fontFamily
          }

          NumberField {
            id: minutesField
            label: "Minutes"
            value: root.customMinutes
            from: 1
            to: Math.floor(Model.MAX_SECONDS / 60)
            stepSize: 5
            foreground: root.barForeground
            fontFamily: root.bar.fontFamily
            fieldWidth: parent.width
            onModified: function(value) { root.customMinutes = value }

            // Without this the field can only be reached by clicking it: the
            // panel's key catcher owns the keyboard until something inside
            // takes focus, so a keyboard user could never type a duration.
            Component.onCompleted: if (root.stage === "custom") field.forceActiveFocus()

            // Enter inside the field commits and engages in one go.
            Connections {
              target: minutesField.field.contentItem
              function onAccepted() { root.request(root.commitMinutes()) }
            }
          }

          Row {
            width: parent.width
            spacing: Style.space(6)

            readonly property real cellWidth: (width - spacing) / 2

            Button {
              width: parent.cellWidth
              text: "Back"
              fontSize: Style.font.bodySmall
              foreground: root.barForeground
              fontFamily: root.bar.fontFamily
              bordered: true
              onClicked: root.resetStage()
            }

            Button {
              width: parent.cellWidth
              text: "Engage"
              fontSize: Style.font.bodySmall
              foreground: root.barForeground
              fontFamily: root.bar.fontFamily
              bordered: true
              onClicked: root.request(root.commitMinutes())
            }
          }
        }

        // --------------------------------------------------------- confirm
        Column {
          visible: root.stage === "confirm"
          width: parent.width
          spacing: Style.space(10)

          PanelSectionHeader {
            text: "CONFIRM"
            foreground: Color.urgent
            fontFamily: root.bar.fontFamily
          }

          Text {
            width: parent.width
            text: "This is a long lock period. Are you sure?"
            color: Color.urgent
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
            wrapMode: Text.WordWrap
          }

          Text {
            width: parent.width
            text: "The session locks for " + Model.formatDuration(root.pendingMinutes)
              + ". There is no password prompt and no cancel — it lifts when the timer runs out."
            color: Qt.darker(root.barForeground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          Row {
            width: parent.width
            spacing: Style.space(6)

            readonly property real cellWidth: (width - spacing) / 2

            Button {
              width: parent.cellWidth
              text: "Cancel"
              fontSize: Style.font.bodySmall
              foreground: root.barForeground
              fontFamily: root.bar.fontFamily
              bordered: true
              onClicked: root.resetStage()
            }

            Button {
              width: parent.cellWidth
              text: "Engage"
              fontSize: Style.font.bodySmall
              foreground: Color.urgent
              accent: Color.urgent
              fontFamily: root.bar.fontFamily
              bordered: true
              onClicked: root.commit(root.pendingMinutes)
            }
          }
        }
      }
    }
  }
}
