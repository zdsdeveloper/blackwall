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

  // The resolution sweep. `probeAt` of 0 means the daemon has not swept yet,
  // which the panel must not draw as "everything clear".
  readonly property var probe: report.probe || ({})
  readonly property real probeAt: Number(report.probe_at || 0)
  readonly property real probeInterval: Number(report.probe_interval_seconds || 300)
  readonly property bool probeSwept: root.probeAt > 0
  readonly property var probeLeaks: report.leaking || []
  readonly property int probeSunk:
    Number((report.probe_summary && report.probe_summary.sunk) || 0)

  readonly property string monoFamily: Style.font.family
  readonly property color ink: "#ff2b34"

  // NetWatch's colours, which are not the wall's. The wall is red because it
  // is the thing being contained; the agency watching it is cold. Used for the
  // mark and the header chrome only -- everything below the rule is about the
  // Blackwall and stays in the Blackwall's colour.
  readonly property color netwatchInk: "#8fd8f2"
  readonly property color netwatchGlow: "#eaf7ff"
  readonly property color dim: Qt.rgba(1, 1, 1, 0.34)

  // ---- the power-on sequence ---------------------------------------------
  //
  // The station comes up rather than appearing. Each element takes its power
  // from a slot in the ramp, so the lamps light in order and the wall arrives
  // after the frame it sits in — about 900ms end to end.

  property real bootProgress: 0

  // ---- the station's clock -------------------------------------------------
  //
  // One timer, thirty steps a second, and every moving thing on the surface is
  // a function of it. Nothing here runs an animation of its own.
  //
  // That is not a style choice. A running QML animation holds the render loop
  // at the display's refresh rate for as long as it runs, and this display is
  // 144Hz: measured on an otherwise identical window, one NumberAnimation cost
  // 115 ticks per ten seconds against 23 for a 30Hz timer doing the same work.
  // Because every animation pays for the same repaint, the costs do not add
  // up and switching off any one of them saved almost nothing -- the whole set
  // had to go for any of it to matter.
  //
  // Wall-clock rather than accumulated, so the station does not drift slow
  // when a frame is late.
  property real clock: 0
  property double clockOrigin: 0
  property real epoch: 0

  // One blink shared by every caret on the surface, so they agree with each
  // other the way a single terminal's would.
  readonly property real caretOn: (root.clock % 1.16) < 0.68 ? 1 : 0

  Timer {
    interval: 33
    repeat: true
    running: window.visible
    onTriggered: {
      root.clock = (Date.now() - root.clockOrigin) / 1000
      // Wall-clock seconds, for anything counting against a timestamp the
      // daemon reported rather than against time since the window opened.
      root.epoch = Date.now() / 1000
    }
  }

  function boot() {
    root.clockOrigin = Date.now()
    root.clock = 0
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

    // Each slot opens a little after the one before it and takes 300ms to come
    // up. The spacing has to leave the last slot a full 300ms of ramp to climb
    // in, or it never reaches full power and simply stays dim forever: at 0.11
    // per slot, slot 9 started at 0.99 and settled at 3% opacity, which is why
    // the console was there but unreadable. At 0.07 every slot still lands in
    // order and every slot finishes lit.
    var start = slot * 0.07
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
    implicitWidth: 1020
    implicitHeight: 860
    color: "#050102"

    onVisibleChanged: if (!visible) root.requestClose()

    Item {
      anchors.fill: parent

      // The static, behind everything, breathing with the wall.
      // The lock wants a field that snaps and tears, because it is a wall
      // coming down. A station someone reads for minutes wants the same field
      // slowed right down and stripped of its loud half — but still a field
      // you can see. Ground too fine it stops being static and becomes an
      // even grey nothing, which is where 2.6 had it.
      GlitchBackground {
        anchors.fill: parent
        running: window.visible
        externalClock: root.clock
        intensity: (1.90 + 0.60 * wall.breath) * root.powerAt(0)
        // Coarser than the lock's, not finer. Ground fine enough and static
        // stops being static: the cells fall below what the eye separates and
        // the whole field averages out to a flat grey nothing. Bigger cells at
        // a low level read as a surface with texture on it, which is the thing
        // that was wanted -- something behind everything, not something
        // demanding attention.
        grainScale: 0.72
        // What the field resamples at. At 2.5 it was visibly stepping, which
        // next to a surface where everything else moves at 30 reads as a
        // stutter rather than as slowness. The clock feeding it ticks 30 times
        // a second, so 15 lands evenly on it.
        stepRate: 15
        artifacts: 0
      }

      // The perimeter trace. Decorative, and the clearest signal from across
      // the room that the post is live.
      StationTrace {
        clock: root.clock
        anchors.fill: parent
        anchors.margins: 6
        power: root.powerAt(1)
        inkColor: root.ink
      }

      Item {
        id: deck
        anchors.fill: parent
        anchors.margins: 18

        // ---- header -------------------------------------------------------

        Item {
          id: header
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          height: 58

          StationWordmark {
            id: brand
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            width: Math.min(320, parent.width * 0.34)
            height: 46
            monoFamily: root.monoFamily
            clock: root.clock
            live: root.daemonAnswering
            topColor: root.netwatchGlow
            footColor: root.netwatchInk
            power: root.powerAt(0)
          }

          Text {
            anchors.left: brand.right
            anchors.leftMargin: 16
            anchors.bottom: brand.bottom
            anchors.bottomMargin: 2
            text: "BLACKWALL MONITOR"
            font.family: root.monoFamily
            font.pixelSize: 10
            font.letterSpacing: 3
            color: Qt.rgba(root.netwatchInk.r, root.netwatchInk.g,
                           root.netwatchInk.b, 0.55)
            opacity: root.powerAt(1)
          }

          // A carrier between the title and the link state. It is the header's
          // share of the motion, and it stops dead when the daemon does.
          StationConduit {
            clock: root.clock
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: brand.right
            anchors.leftMargin: 24
            anchors.right: link.left
            anchors.rightMargin: 24
            anchors.verticalCenterOffset: -12
            height: 16
            flow: "across"
            lanes: 1
            speed: root.daemonAnswering ? 1.6 : 0.15
            power: root.powerAt(1)
            inkColor: root.netwatchInk
          }

          Text {
            id: link
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            text: (root.daemonAnswering ? "LINK ESTABLISHED" : "NO LINK")
              + "   ──   CYCLE " + root.intervalSeconds + "s"
            font.family: root.monoFamily
            font.pixelSize: 11
            font.letterSpacing: 2
            color: root.daemonAnswering
              ? Qt.rgba(root.netwatchInk.r, root.netwatchInk.g,
                        root.netwatchInk.b, 0.62)
              : Qt.rgba(1, 0.72, 0.28, 0.9)
            opacity: root.powerAt(1)
          }

          // The rule under the header is where NetWatch stops and the wall
          // begins: cold above it, the wall's red below.
          Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Qt.rgba(root.netwatchInk.r, root.netwatchInk.g,
                           root.netwatchInk.b, 0.30 * root.powerAt(1))
          }
        }

        // ---- the wall itself ----------------------------------------------
        //
        // The centrepiece, not an item in a column. Everything else on the
        // station is a readout about this; putting it in the corner said the
        // opposite. The boards either side are there because the wall alone
        // left the widest part of the window empty.

        Item {
          id: hero
          anchors.top: header.bottom
          anchors.topMargin: 8
          anchors.left: parent.left
          anchors.right: parent.right
          height: Math.max(132, Math.min(238, Math.round(parent.height * 0.26)))

          StationConduit {

            clock: root.clock
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: Math.round(parent.width * 0.21)
            flow: "down"
            lanes: 5
            packetSpacing: 58
            speed: root.daemonAnswering ? 1.0 : 0.2
            power: root.powerAt(2) * 0.5
            inkColor: root.ink
          }

          StationConduit {

            clock: root.clock
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: Math.round(parent.width * 0.21)
            flow: "down"
            lanes: 5
            packetSpacing: 58
            speed: root.daemonAnswering ? 1.15 : 0.2
            power: root.powerAt(2) * 0.5
            inkColor: root.ink
          }

          StationGyro {

            clock: root.clock
            anchors.centerIn: parent
            scaleUnit: hero.height * 1.12
            steady: root.daemonAnswering
            power: root.powerAt(3)
            inkColor: root.ink
          }

          BlackwallWall {
            id: wall
            anchors.centerIn: parent
            active: window.visible
            clock: root.clock
            monoFamily: root.monoFamily
            availableWidth: hero.width
            availableHeight: hero.height
            heightFraction: 0.60
            widthFraction: 0.42
            // Twelve updates a second instead of sixty. The ripple is a slow
            // bloom; nobody was ever going to see the difference, and it is
            // most of what the wall costs.
            rippleSteps: 32
            opacity: root.powerAt(4)
          }
        }

        // ---- the console ---------------------------------------------------
        //
        // Pinned to the bottom and given real room, because it is the only
        // part of the station that answers "what has actually happened".

        StationFrame {

          clock: root.clock
          id: consoleFrame
          anchors.bottom: parent.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          height: Math.max(140, Math.min(300, Math.round(parent.height * 0.27)))
          title: "CONSOLE"
          annotation: root.logEntries.length + " ENTRIES"
          font.family: root.monoFamily
          power: root.powerAt(9)
          inkColor: root.ink
          padding: 10

          StationConsole {

            clock: root.clock
            anchors.fill: parent
            entries: root.logEntries
            font.family: root.monoFamily
            lineSize: 11
            power: root.powerAt(9)
            inkColor: root.ink
          }
        }

        // ---- the instrument strip -------------------------------------------

        Row {
          id: instruments
          anchors.bottom: consoleFrame.top
          anchors.bottomMargin: 18
          anchors.left: parent.left
          anchors.right: parent.right
          height: 104
          spacing: 18

          readonly property real cell: (width - 36) / 3

          StationFrame {

            clock: root.clock
            width: instruments.cell
            height: instruments.height
            title: "SIGNAL"
            annotation: root.daemonAnswering ? "NOMINAL" : "LOST"
            alert: !root.daemonAnswering && root.everAnswered
            font.family: root.monoFamily
            power: root.powerAt(6)
            inkColor: root.ink

            StationWave {

              clock: root.clock
              anchors.fill: parent
              power: root.powerAt(6)
              inkColor: root.ink
              bars: 52
              agitated: root.everAnswered && !root.intact
              speed: root.daemonAnswering ? 1 : 0.3
            }
          }

          StationFrame {

            clock: root.clock
            width: instruments.cell
            height: instruments.height
            title: "RESOLVER"
            annotation: root.probeSwept
              ? root.probeSunk + "/" + root.domains.length + " SUNK"
              : "NOT SWEPT"
            alert: root.probeLeaks.length > 0
            font.family: root.monoFamily
            power: root.powerAt(7)
            inkColor: root.ink

            // Not another length of pipe. This one is answering a question
            // nothing else on the station answers: where do these names
            // actually resolve to, right now, on this machine.
            StationBus {
              anchors.fill: parent
              clock: root.clock
              epoch: root.epoch
              domains: root.domains
              results: root.probe
              sweptAt: root.probeAt
              interval: root.probeInterval
              power: root.powerAt(7)
              inkColor: root.ink
              font.family: root.monoFamily
            }
          }

          StationFrame {

            clock: root.clock
            width: instruments.cell
            height: instruments.height
            title: "INDEX"
            font.family: root.monoFamily
            power: root.powerAt(8)
            inkColor: root.ink
            live: false

            Column {
              anchors.fill: parent
              spacing: 0

              StationMeter {

                clock: root.clock
                width: parent.width
                label: "SINK LINES"
                // Four per subject: two families, two forms of the name.
                value: String(root.domains.length * 4)
                font.family: root.monoFamily
                power: root.powerAt(8)
                inkColor: root.ink
              }

              StationMeter {

                clock: root.clock
                width: parent.width
                label: "BREACHES"
                value: String(Number(root.report.breaches || 0))
                alert: Number(root.report.breaches || 0) > 0
                font.family: root.monoFamily
                power: root.powerAt(8)
                inkColor: root.ink
              }

              StationMeter {

                clock: root.clock
                width: parent.width
                label: "FAULTS"
                value: String(Number(root.report.enforce_failures || 0))
                alert: Number(root.report.enforce_failures || 0) > 0
                font.family: root.monoFamily
                power: root.powerAt(8)
                inkColor: root.ink
              }
            }
          }
        }

        // ---- the three columns --------------------------------------------

        Row {
          id: columns
          anchors.top: hero.bottom
          anchors.topMargin: 18
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: instruments.top
          anchors.bottomMargin: 18
          spacing: 18

          readonly property real usable: width - 36

          // ---------------------------------------------------- SUBJECT
          StationFrame {
            clock: root.clock
            width: Math.round(columns.usable * 0.28)
            height: columns.height
            title: "SUBJECT"
            alert: root.everAnswered && !root.intact
            font.family: root.monoFamily
            power: root.powerAt(5)
            inkColor: root.ink

            Column {
              id: subjectStack
              anchors.top: parent.top
              anchors.left: parent.left
              anchors.right: parent.right
              spacing: 10

              StationLamp {

                clock: root.clock
                lamp: !root.everAnswered ? "idle" : (root.intact ? "lit" : "dark")
                label: !root.everAnswered ? "INTEGRITY  ····" : (root.intact ? "INTEGRITY  INTACT" : "INTEGRITY  WEAKENED")
                monoFamily: root.monoFamily
                scaleUnit: 13
                power: root.powerAt(5)
              }

              StationLamp {

                clock: root.clock
                lamp: root.daemonAnswering ? "lit" : "dark"
                label: "ENFORCING  " + (root.daemonAnswering ? "ACTIVE" : "SILENT")
                monoFamily: root.monoFamily
                scaleUnit: 13
                power: root.powerAt(6)
              }

              Rectangle {
                width: parent.width
                height: 1
                color: Qt.rgba(1, 0.24, 0.28, 0.16)
              }

              StationMeter {

                clock: root.clock
                width: parent.width
                label: "SUBJECTS"
                value: String(root.domains.length)
                font.family: root.monoFamily
                power: root.powerAt(6)
                inkColor: root.ink
              }

              StationMeter {

                clock: root.clock
                width: parent.width
                label: "ENFORCED"
                value: String(root.live.length)
                alert: root.everAnswered && root.live.length < root.domains.length
                font.family: root.monoFamily
                power: root.powerAt(6)
                inkColor: root.ink
              }

              StationMeter {

                clock: root.clock
                width: parent.width
                label: "CYCLE"
                value: root.intervalSeconds + "s"
                font.family: root.monoFamily
                power: root.powerAt(7)
                inkColor: root.ink
              }

              // Every reason the wall is weaker than it should be, in the
              // words the daemon used. No summary: the operator gets the
              // finding.
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

          }

          // ------------------------------------------------ CONTAINMENT
          StationFrame {
            clock: root.clock
            id: containment
            width: Math.round(columns.usable * 0.44)
            height: columns.height
            title: "CONTAINMENT"
            annotation: String(root.domains.length)
            font.family: root.monoFamily
            power: root.powerAt(5)
            inkColor: root.ink

            // One row per contained subject. The lamp is lit only when that
            // block is verified present in the hosts file right now — not when
            // the blocklist claims it. A subject listed but not enforced is
            // exactly what the operator needs to see.
            Flickable {
              id: roll
              anchors.top: parent.top
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.bottom: commit.top
              anchors.bottomMargin: 12
              contentHeight: subjects.height
              clip: true

              Column {
                id: subjects
                width: roll.width
                spacing: 4

                Repeater {
                  model: root.domains

                  delegate: Rectangle {
                    id: subject
                    required property var modelData
                    required property int index

                    width: subjects.width
                    height: 26
                    color: hover.hovered ? Qt.rgba(1, 0.24, 0.28, 0.09) : "transparent"

                    readonly property bool enforced: root.live.indexOf(subject.modelData) !== -1

                    HoverHandler { id: hover }

                    StationLamp {

                      clock: root.clock
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
                      color: subject.enforced ? Qt.rgba(1, 0.58, 0.60, 1) : Qt.rgba(1, 1, 1, 0.35)
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
              id: commit
              anchors.bottom: parent.bottom
              anchors.left: parent.left
              anchors.right: parent.right
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
                height: 32
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

                // The caret, so an empty field still reads as a prompt waiting
                // for something rather than a box.
                Rectangle {
                  visible: field.activeFocus && field.text === ""
                  x: 8
                  anchors.verticalCenter: parent.verticalCenter
                  width: 7
                  height: 14
                  color: root.ink
                  opacity: root.caretOn
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
          StationFrame {
            clock: root.clock
            width: columns.usable - Math.round(columns.usable * 0.28)
                   - Math.round(columns.usable * 0.44)
            height: columns.height
            title: "TELEMETRY"
            font.family: root.monoFamily
            power: root.powerAt(5)
            inkColor: root.ink

            Column {
              id: telemetryStack
              anchors.top: parent.top
              anchors.left: parent.left
              anchors.right: parent.right
              spacing: 10

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

                // Two notches, and the second is a locked screen. Capacity,
                // not a percentage — the shape says how much room is left.
                StationBar {
                  width: parent.width
                  segments: 2
                  scaleUnit: 20
                  level: Math.min(1, root.unacked / 2)
                  critical: root.unacked >= 2
                  power: root.powerAt(4)
                }

                Text {
                  text: root.unacked === 0
                    ? "clear"
                    : (root.unacked === 1 ? "one unanswered — next locks" : "locked on next breach")
                  width: parent.width
                  wrapMode: Text.WordWrap
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
                  scaleUnit: 16
                  power: root.powerAt(5)
                }
              }

              Rectangle {
                width: parent.width
                height: 1
                color: Qt.rgba(1, 0.24, 0.28, 0.16)
              }

              StationLamp {

                clock: root.clock
                lamp: !root.everAnswered ? "idle" : (root.report.doh_locked ? "lit" : "dark")
                label: "DoH LOCKED"
                monoFamily: root.monoFamily
                scaleUnit: 13
                power: root.powerAt(6)
              }

              StationLamp {

                clock: root.clock
                lamp: !root.everAnswered ? "idle" : (root.report.unit_intact ? "lit" : "dark")
                label: "UNIT INTACT"
                monoFamily: root.monoFamily
                scaleUnit: 13
                power: root.powerAt(7)
              }

              // Three-state on purpose. A filesystem that cannot report the
              // flag is not a ledger that lost it, and showing them alike
              // would send the operator hunting a breach that never happened.
              StationLamp {
                clock: root.clock
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

                clock: root.clock
                lamp: Number(root.report.enforce_failures || 0) > 0 ? "unknown" : "idle"
                label: "FAULTS  " + Number(root.report.enforce_failures || 0)
                monoFamily: root.monoFamily
                scaleUnit: 13
                power: root.powerAt(8)
              }
            }

            StationConduit {

              clock: root.clock
              anchors.top: telemetryStack.bottom
              anchors.topMargin: 14
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.bottom: parent.bottom
              visible: height > 30
              flow: "down"
              lanes: 3
              speed: root.daemonAnswering ? 1.4 : 0.15
              power: root.powerAt(8) * 0.62
              inkColor: root.ink
            }
          }
        }
      }
    }
  }

}
