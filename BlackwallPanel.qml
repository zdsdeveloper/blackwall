pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "Model.js" as Model

// The NetWatch station.
//
// Not a settings window with a theme on it. The operator is at a post, watching
// the wall — so a domain is a contained subject rather than a list row, the
// ladder is threat state rather than a preference, and the readouts nobody acts
// on are there because a real station carries them.
//
// Everything the station shows is read out of the daemon. Nothing here can
// weaken anything: the only verb the surface offers is containing one more.
Item {
  id: root

  // ---- plugin lifecycle, as the host expects it --------------------------
  property bool closingFromHost: false

  function open(payloadJson) {
    closingFromHost = false
    window.visible = true
    root.boot()
  }

  function close() {
    closingFromHost = true
    window.visible = false
    closingFromHost = false
  }

  function requestClose() {
    if (root.closingFromHost) return
    window.visible = false
  }

  // ---- live state ---------------------------------------------------------

  property var report: ({})
  property var logEntries: []
  property bool everAnswered: false
  property bool daemonAnswering: false

  readonly property var domains: report.domains_list || []
  readonly property var live: report.blocked_live || []
  readonly property int unacked: Number(report.unacknowledged || 0)
  readonly property var weakReasons: report.weakened || []
  readonly property bool intact: root.everAnswered && root.weakReasons.length === 0
  readonly property int intervalSeconds: Number(report.interval_seconds || 30)

  readonly property string monoFamily: Style.font.family
  readonly property color ink: "#ff2b34"
  readonly property color dim: Qt.rgba(1, 1, 1, 0.34)

  // ---- the power-on sequence ---------------------------------------------
  //
  // The station comes up rather than appearing. Each element takes its power
  // from a slot in the ramp, so the lamps light in order and the wall arrives
  // after the frame it sits in — about 900ms end to end.

  property real bootProgress: 0

  function boot() {
    root.bootProgress = 0
    bootRamp.restart()
    root.poll()
  }

  function powerAt(slot) {
    // A station nobody is looking at draws no power. Every animation on the
    // surface is gated on its slot's power, so this one line stops all of
    // them when the window closes -- without it the gyro, the perimeter
    // trace and the lamp halos keep running forever after the first open,
    // because the boot ramp settles above zero and stays there.
    //
    // Reading window.visible here is what makes the callers' bindings depend
    // on it; QML tracks property reads through the call.
    if (!window.visible) return 0

    // Each slot opens a fifth of a second after the one before it and takes
    // 300ms to come up.
    var start = slot * 0.11
    return Model.clamp((root.bootProgress - start) / 0.30, 0, 1)
  }

  NumberAnimation {
    id: bootRamp
    target: root
    property: "bootProgress"
    from: 0
    to: 1
    duration: 900
    easing.type: Easing.OutCubic
  }

  // ---- talking to the daemon ---------------------------------------------

  function poll() {
    if (!statusProc.running) statusProc.running = true
    if (!logProc.running) logProc.running = true
  }

  Timer {
    interval: 2000
    repeat: true
    running: window.visible
    triggeredOnStart: true
    onTriggered: root.poll()
  }

  Process {
    id: statusProc
    command: ["netwatchctl", "status", "--json"]
    stdout: StdioCollector { id: statusOut; waitForEnd: true }
    onExited: function (code, status) {
      if (code !== 0) {
        root.daemonAnswering = false
        return
      }
      try {
        root.report = JSON.parse(String(statusOut.text || "{}"))
        root.daemonAnswering = true
        root.everAnswered = true
        // One bar per poll that actually landed. A heartbeat that kept beating
        // after the daemon stopped answering would be worse than none.
        spark.push(root.weakReasons.length > 0 ? 1.0 : 0.28,
                   Number(root.report.enforce_failures || 0) > 0)
      } catch (e) {
        root.daemonAnswering = false
      }
    }
  }

  Process {
    id: logProc
    command: ["netwatchctl", "log", "--limit", "40"]
    stdout: StdioCollector { id: logOut; waitForEnd: true }
    onExited: function (code, status) {
      if (code !== 0) return
      try {
        var parsed = JSON.parse(String(logOut.text || "[]"))
        root.logEntries = Array.isArray(parsed) ? parsed : []
      } catch (e) { /* a tail that will not parse is simply not shown */ }
    }
  }

  // ---- containing a domain ------------------------------------------------

  property string commitState: "idle"   // idle | working | done | refused
  property string commitMessage: ""
  property real commitProgress: 0

  function contain(raw) {
    var text = String(raw || "").trim()
    if (text === "") return
    root.commitState = "working"
    root.commitMessage = ""
    root.commitProgress = 0
    commitRamp.restart()
    addProc.command = ["netwatchctl", "add", text]
    addProc.running = true
  }

  NumberAnimation {
    id: commitRamp
    target: root
    property: "commitProgress"
    from: 0
    // Stops short of full: the bar completes when the daemon answers, not when
    // an animation decides it has been long enough.
    to: 0.75
    duration: 900
  }

  Process {
    id: addProc
    stderr: StdioCollector { id: addErr; waitForEnd: true }
    onExited: function (code, status) {
      commitRamp.stop()
      root.commitProgress = 1
      if (code === 0) {
        root.commitState = "done"
        root.commitMessage = "CONTAINED"
        field.text = ""
      } else {
        root.commitState = "refused"
        root.commitMessage = String(addErr.text || "").trim().toUpperCase() || "REFUSED"
      }
      root.poll()
      settle.restart()
    }
  }

  Timer {
    id: settle
    interval: 2600
    onTriggered: {
      root.commitState = "idle"
      root.commitMessage = ""
      root.commitProgress = 0
    }
  }

  // ---- the window ---------------------------------------------------------

  FloatingWindow {
    id: window
    title: "NetWatch — Blackwall Monitor"
    implicitWidth: 940
    implicitHeight: 700
    color: "#050102"

    onVisibleChanged: if (!visible) root.requestClose()

    Item {
      anchors.fill: parent

      // The static, behind everything, breathing with the wall.
      // Sand, not snow. The lock wants a field that snaps and tears because
      // it is a wall coming down; a station someone reads for minutes at a
      // time wants something that drifts and never asks to be looked at.
      GlitchBackground {
        anchors.fill: parent
        running: window.visible
        intensity: (0.20 + 0.10 * wall.breath) * root.powerAt(0)
        grainScale: 2.6
        stepRate: 2.5
        artifacts: 0
      }

      // The perimeter trace. Decorative, and the clearest signal from across
      // the room that the post is live.
      StationTrace {
        anchors.fill: parent
        anchors.margins: 6
        power: root.powerAt(1)
        inkColor: root.ink
      }

      Item {
        anchors.fill: parent
        anchors.margins: 22

        // ---- header -------------------------------------------------------
        Item {
          id: header
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          height: 26

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "NETWATCH  ──  BLACKWALL MONITOR"
            font.family: root.monoFamily
            font.pixelSize: 13
            font.bold: true
            font.letterSpacing: 3
            color: root.ink
            opacity: root.powerAt(0)
          }

          Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            text: (root.daemonAnswering ? "LINK ESTABLISHED" : "NO LINK")
              + "   ──   CYCLE " + root.intervalSeconds + "s"
            font.family: root.monoFamily
            font.pixelSize: 11
            font.letterSpacing: 2
            color: root.daemonAnswering ? root.dim : Qt.rgba(1, 0.72, 0.28, 0.9)
            opacity: root.powerAt(1)
          }

          Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Qt.rgba(1, 0.24, 0.28, 0.25 * root.powerAt(1))
          }
        }

        // ---- the wall itself ----------------------------------------------
        //
        // The centrepiece, not an item in a column. Everything else on the
        // station is a readout about this; putting it in the corner said the
        // opposite.
        Item {
          id: hero
          anchors.top: header.bottom
          anchors.topMargin: 10
          anchors.left: parent.left
          anchors.right: parent.right
          // 186 at the size the window opens at, and gives ground when
          // someone drags it smaller -- the tail takes a fixed 22% and the
          // header is fixed, so a fixed hero is what pushes the columns to a
          // negative height on a short window.
          height: Math.max(96, Math.min(186, Math.round(parent.height * 0.30)))

          StationGyro {
            anchors.centerIn: parent
            scaleUnit: hero.height * 1.02
            steady: root.daemonAnswering
            power: root.powerAt(3) * 0.7
            inkColor: root.ink
          }

          BlackwallWall {
            id: wall
            anchors.centerIn: parent
            active: window.visible
            monoFamily: root.monoFamily
            availableWidth: hero.width
            availableHeight: hero.height
            heightFraction: 0.52
            widthFraction: 0.34
            opacity: root.powerAt(4)
          }
        }

        // ---- the three columns --------------------------------------------
        Row {
          anchors.top: hero.bottom
          anchors.topMargin: 16
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: tail.top
          anchors.bottomMargin: 14
          spacing: 22

          // ---------------------------------------------------- SUBJECT
          Column {
            width: Math.round((parent.width - 44) * 0.30)
            height: parent.height
            spacing: 12

            Text {
              text: "SUBJECT"
              font.family: root.monoFamily
              font.pixelSize: 10
              font.letterSpacing: 3
              color: root.dim
              opacity: root.powerAt(2)
            }

            StationLamp {
              lamp: !root.everAnswered ? "idle" : (root.intact ? "lit" : "dark")
              label: !root.everAnswered ? "INTEGRITY  ····" : (root.intact ? "INTEGRITY  INTACT" : "INTEGRITY  WEAKENED")
              monoFamily: root.monoFamily
              scaleUnit: 13
              power: root.powerAt(5)
            }

            StationLamp {
              lamp: root.daemonAnswering ? "lit" : "dark"
              label: "ENFORCING  " + (root.daemonAnswering ? "ACTIVE" : "SILENT")
              monoFamily: root.monoFamily
              scaleUnit: 13
              power: root.powerAt(6)
            }

            // Every reason the wall is weaker than it should be, in the words
            // the daemon used. No summary: the operator gets the finding.
            Repeater {
              model: root.weakReasons

              delegate: Text {
                required property var modelData
                width: parent ? parent.width : 0
                wrapMode: Text.WordWrap
                text: "▸ " + modelData
                font.family: root.monoFamily
                font.pixelSize: 10
                color: Qt.rgba(1, 0.42, 0.45, 1)
                opacity: root.powerAt(6)
              }
            }
          }

          // ------------------------------------------------ CONTAINMENT
          Column {
            width: Math.round((parent.width - 44) * 0.40)
            height: parent.height
            spacing: 10

            Text {
              text: "CONTAINMENT  ──  " + root.domains.length
              font.family: root.monoFamily
              font.pixelSize: 10
              font.letterSpacing: 3
              color: root.dim
              opacity: root.powerAt(2)
            }

            // One row per contained subject. The lamp is lit only when that
            // block is verified present in the hosts file right now — not when
            // the blocklist claims it. A subject listed but not enforced is
            // exactly what the operator needs to see.
            Flickable {
              width: parent.width
              height: parent.height - 132
              contentHeight: subjects.height
              clip: true

              Column {
                id: subjects
                width: parent.width
                spacing: 4

                Repeater {
                  model: root.domains

                  delegate: Rectangle {
                    id: subject
                    required property var modelData
                    required property int index

                    width: subjects.width
                    height: 24
                    color: hover.hovered ? Qt.rgba(1, 0.24, 0.28, 0.07) : "transparent"

                    readonly property bool enforced: root.live.indexOf(subject.modelData) !== -1

                    HoverHandler { id: hover }

                    StationLamp {
                      anchors.verticalCenter: parent.verticalCenter
                      anchors.left: parent.left
                      anchors.leftMargin: 4
                      lamp: subject.enforced ? "lit" : "dark"
                      label: ""
                      scaleUnit: 12
                      power: root.powerAt(5 + Math.min(6, subject.index * 0.4))
                    }

                    Text {
                      anchors.verticalCenter: parent.verticalCenter
                      anchors.left: parent.left
                      anchors.leftMargin: 26
                      text: subject.modelData
                      font.family: root.monoFamily
                      font.pixelSize: 12
                      color: subject.enforced ? Qt.rgba(1, 0.52, 0.55, 1) : Qt.rgba(1, 1, 1, 0.35)
                      opacity: root.powerAt(5 + Math.min(6, subject.index * 0.4))
                    }

                    Text {
                      anchors.verticalCenter: parent.verticalCenter
                      anchors.right: parent.right
                      anchors.rightMargin: 6
                      text: subject.enforced ? "CONTAINED" : "NOT ENFORCED"
                      font.family: root.monoFamily
                      font.pixelSize: 9
                      font.letterSpacing: 1
                      color: subject.enforced ? root.dim : Qt.rgba(1, 0.72, 0.28, 0.9)
                      opacity: root.powerAt(5 + Math.min(6, subject.index * 0.4))
                    }

                    Rectangle {
                      anchors.bottom: parent.bottom
                      width: parent.width
                      height: 1
                      color: Qt.rgba(1, 0.24, 0.28, 0.10)
                    }
                  }
                }
              }
            }

            // ---- the only verb the station offers
            Column {
              width: parent.width
              spacing: 6

              Text {
                text: "> CONTAIN"
                font.family: root.monoFamily
                font.pixelSize: 10
                font.letterSpacing: 2
                color: root.dim
                opacity: root.powerAt(7)
              }

              Rectangle {
                width: parent.width
                height: 30
                color: "#0d0203"
                border.width: 1
                border.color: field.activeFocus
                  ? root.ink
                  : Qt.rgba(1, 0.24, 0.28, 0.30)
                opacity: root.powerAt(7)

                TextInput {
                  id: field
                  anchors.fill: parent
                  anchors.margins: 8
                  font.family: root.monoFamily
                  font.pixelSize: 12
                  color: "#ff6b70"
                  selectionColor: root.ink
                  selectedTextColor: "#000000"
                  selectByMouse: true
                  clip: true
                  enabled: root.commitState !== "working"
                  onAccepted: root.contain(field.text)
                }
              }

              StationBar {
                width: parent.width
                segments: 28
                scaleUnit: 12
                level: root.commitProgress
                working: root.commitState === "working"
                critical: root.commitState === "refused"
                power: root.powerAt(7)
              }

              Text {
                text: root.commitMessage
                font.family: root.monoFamily
                font.pixelSize: 10
                font.letterSpacing: 1
                color: root.commitState === "refused"
                  ? Qt.rgba(1, 0.72, 0.28, 1)
                  : root.dim
                opacity: root.commitMessage === "" ? 0 : 1
                Behavior on opacity { NumberAnimation { duration: 200 } }
              }
            }
          }

          // -------------------------------------------------- TELEMETRY
          Column {
            width: parent.width - Math.round((parent.width - 44) * 0.70) - 44
            height: parent.height
            spacing: 12

            Text {
              text: "TELEMETRY"
              font.family: root.monoFamily
              font.pixelSize: 10
              font.letterSpacing: 3
              color: root.dim
              opacity: root.powerAt(2)
            }

            Column {
              width: parent.width
              spacing: 4

              Text {
                text: "RUNG"
                font.family: root.monoFamily
                font.pixelSize: 10
                font.letterSpacing: 2
                color: root.dim
                opacity: root.powerAt(4)
              }

              // Two notches, and the second is a locked screen. Capacity, not
              // a percentage — the shape says how much room is left.
              StationBar {
                width: parent.width
                segments: 2
                scaleUnit: 18
                level: Math.min(1, root.unacked / 2)
                critical: root.unacked >= 2
                power: root.powerAt(4)
              }

              Text {
                text: root.unacked === 0
                  ? "clear"
                  : (root.unacked === 1 ? "one unanswered — next locks" : "locked on next breach")
                font.family: root.monoFamily
                font.pixelSize: 9
                color: root.unacked >= 1 ? Qt.rgba(1, 0.72, 0.28, 0.9) : root.dim
                opacity: root.powerAt(4)
              }
            }

            Column {
              width: parent.width
              spacing: 4

              Text {
                text: "CYCLE"
                font.family: root.monoFamily
                font.pixelSize: 10
                font.letterSpacing: 2
                color: root.dim
                opacity: root.powerAt(5)
              }

              StationSpark {
                id: spark
                width: parent.width
                bars: 26
                scaleUnit: 14
                power: root.powerAt(5)
              }
            }

            Item { width: 1; height: 6 }

            StationLamp {
              lamp: !root.everAnswered ? "idle" : (root.report.doh_locked ? "lit" : "dark")
              label: "DoH LOCKED"
              monoFamily: root.monoFamily
              scaleUnit: 13
              power: root.powerAt(6)
            }

            StationLamp {
              lamp: !root.everAnswered ? "idle" : (root.report.unit_intact ? "lit" : "dark")
              label: "UNIT INTACT"
              monoFamily: root.monoFamily
              scaleUnit: 13
              power: root.powerAt(7)
            }

            // Three-state on purpose. A filesystem that cannot report the flag
            // is not a ledger that lost it, and showing them alike would send
            // the operator hunting a breach that never happened.
            StationLamp {
              lamp: {
                if (!root.everAnswered) return "idle"
                var sealed = root.report.ledger_sealed
                if (sealed === null || sealed === undefined) return "unknown"
                return sealed ? "lit" : "dark"
              }
              label: "LEDGER SEALED"
              monoFamily: root.monoFamily
              scaleUnit: 13
              power: root.powerAt(8)
            }

            StationLamp {
              lamp: Number(root.report.enforce_failures || 0) > 0 ? "unknown" : "idle"
              label: "FAULTS  " + Number(root.report.enforce_failures || 0)
              monoFamily: root.monoFamily
              scaleUnit: 13
              power: root.powerAt(8)
            }
          }
        }

        // ---- the ledger, tailing -------------------------------------------
        Item {
          id: tail
          anchors.bottom: parent.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          height: Math.round(parent.height * 0.22)

          Rectangle {
            anchors.top: parent.top
            width: parent.width
            height: 1
            color: Qt.rgba(1, 0.24, 0.28, 0.25 * root.powerAt(8))
          }

          Flickable {
            anchors.fill: parent
            anchors.topMargin: 8
            contentHeight: entries.height
            clip: true

            Column {
              id: entries
              width: parent.width
              spacing: 2

              Repeater {
                model: root.logEntries

                delegate: Text {
                  required property var modelData
                  text: Model.stationLogLine(modelData)
                  font.family: root.monoFamily
                  font.pixelSize: 10
                  color: modelData.kind === "breach"
                    ? Qt.rgba(1, 0.42, 0.45, 1)
                    : Qt.rgba(1, 1, 1, 0.30)
                  opacity: root.powerAt(9)
                }
              }
            }
          }
        }
      }
    }
  }
}
