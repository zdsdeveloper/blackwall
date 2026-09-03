pragma ComponentBehavior: Bound

import QtQuick

// Rogue intelligences coming down the outside of the wall. Click one and it
// goes.
//
// This is a toy and makes no claim to be anything else — nothing here reads or
// changes any state the daemon owns, and a ghost reaching the bottom costs
// nothing. It sits where the conduits used to, either side of the wall, on the
// grounds that a length of pipe was decoration too and this is better company
// while you wait for a sweep.
//
// The fiction is at least consistent: things drifting down out of the Blackwall
// are exactly what a NetWatch post would be watching for, and the ones that get
// past you simply pass out of your sector.
Item {
  id: root

  property real power: 1
  property real clock: 0
  property color inkColor: "#ff2b34"
  property string monoFamily: "monospace"

  property int lanes: 3
  // Pixels a second. Slow on purpose: the drop is the whole play, and a ghost
  // that crosses a 240px column in seven seconds can actually be hit.
  property real fallRate: 34
  property real spawnEvery: 2.2
  // Kills, for whoever is counting.
  property int purged: 0

  // Five faces, each three rows of five columns so they sit square in a
  // monospace cell. Padding matters: a ragged row would lean the face.
  readonly property var faces: [
    ["╔═══╗", "║▚ ▞║", "╚═╤═╝"],
    ["▄▄▄▄▄", "█▘ ▝█", "▀▄▄▄▀"],
    ["┌─┬─┐", "│▓ ▓│", "└─┴─┘"],
    ["▟▀▀▀▚", "▌◤ ◥▐", "▜▄▄▄▛"],
    ["╭───╮", "│▪▄▪│", "╰─┴─╯"]
  ]

  readonly property real glyphSize: 13
  readonly property real burstSeconds: 0.42

  ListModel { id: swarm }

  // A ListModel rather than an array of records, so hitting one ghost changes
  // that ghost instead of rebuilding every delegate on the column.
  function spawn() {
    if (root.power <= 0 || root.width <= 0 || swarm.count > 12) return
    swarm.append({
      born: root.clock,
      lane: Math.floor(Math.random() * root.lanes),
      face: Math.floor(Math.random() * root.faces.length),
      dying: false,
      diedAt: 0
    })
  }

  function reap() {
    for (var i = swarm.count - 1; i >= 0; i--) {
      var g = swarm.get(i)
      if (g.dying) {
        if (root.clock - g.diedAt > root.burstSeconds) swarm.remove(i)
      } else if ((root.clock - g.born) * root.fallRate > root.height) {
        // Out of the sector. No score, no penalty.
        swarm.remove(i)
      }
    }
  }

  Timer {
    interval: Math.max(400, Math.round(root.spawnEvery * 1000))
    repeat: true
    running: root.power > 0 && root.visible
    onTriggered: root.spawn()
  }

  Timer {
    interval: 250
    repeat: true
    running: root.power > 0 && root.visible
    onTriggered: root.reap()
  }

  Repeater {
    model: swarm

    delegate: Item {
      id: ghost

      required property int index
      required property real born
      required property int lane
      required property int face
      required property bool dying
      required property real diedAt

      readonly property real laneWidth: root.width / Math.max(1, root.lanes)
      readonly property real fallen: (root.clock - ghost.born) * root.fallRate
      // 0 while alive, 0..1 across the burst.
      readonly property real burst: ghost.dying
        ? Math.min(1, (root.clock - ghost.diedAt) / root.burstSeconds)
        : 0

      width: ghost.laneWidth
      height: root.glyphSize * 3.2
      x: ghost.lane * ghost.laneWidth
      y: ghost.fallen
      // Fades in over the first few pixels so nothing pops into being at the
      // top edge, and dims toward the bottom as it leaves the sector.
      opacity: root.power
        * Math.min(1, ghost.fallen / 18)
        * (1 - ghost.burst)
        * (ghost.dying ? 1 : Math.min(1, (root.height - ghost.fallen) / 26))

      Column {
        id: body
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 0
        scale: 1 + ghost.burst * 0.9

        Repeater {
          model: 3

          delegate: Text {
            id: strip
            required property int index
            text: root.faces[ghost.face][strip.index]
            font.family: root.monoFamily
            font.pixelSize: root.glyphSize
            color: root.inkColor
            // Goes white as it comes apart.
            Behavior on color { ColorAnimation { duration: 120 } }
          }
        }
      }

      // The pieces flying off. Eight is enough to read as a break-up and few
      // enough that a column full of them costs nothing.
      Repeater {
        model: ghost.dying ? 8 : 0

        delegate: Rectangle {
          id: shard
          required property int index
          readonly property real angle: shard.index / 8 * 2 * Math.PI
          readonly property real reach: ghost.burst * 26

          width: 3
          height: 3
          color: root.inkColor
          x: body.x + body.width / 2 + Math.cos(shard.angle) * shard.reach - 1.5
          y: body.height / 2 + Math.sin(shard.angle) * shard.reach - 1.5
          opacity: 1 - ghost.burst
        }
      }

      MouseArea {
        anchors.fill: body
        enabled: !ghost.dying
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          swarm.setProperty(ghost.index, "diedAt", root.clock)
          swarm.setProperty(ghost.index, "dying", true)
          root.purged += 1
        }
      }
    }
  }

  // The tally, for whoever is counting. Deliberately the quietest thing on the
  // column: it is a toy score, not a reading.
  Text {
    anchors.bottom: parent.bottom
    anchors.horizontalCenter: parent.horizontalCenter
    visible: root.purged > 0
    text: "PURGED " + root.purged
    font.family: root.monoFamily
    font.pixelSize: 9
    font.letterSpacing: 2
    color: Qt.rgba(1, 1, 1, 0.28)
    opacity: root.power
  }
}
