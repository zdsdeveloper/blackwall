import QtQuick
import "Faces.js" as Faces
import "Model.js" as Model

// The rogue AIs on the other side, coming up against the wall while it opens.
//
// A fixed pool of apparition slots, each running its own independent cycle:
// pick a face, pick somewhere to be, swell up out of nothing, hold, sink
// back. Nothing is synchronised between slots, so the layer never pulses in
// unison — which is what would make it read as an effect rather than as
// something looking in.
//
// `pressure` scales the whole layer's presence. The individual cycles keep
// running underneath it, so faces are already mid-appearance when the layer
// comes up rather than all starting together.
Item {
  id: root

  property bool active: false

  // 0..1 — how hard they are pressing. See Model.facePressure().
  property real pressure: 0

  // Faint on purpose. These should register as something half-seen at the
  // edge of attention, not as a jump scare.
  readonly property real peakOpacity: 0.26
  readonly property color faceColor: "#d9aeb2"

  property string fontFamily: "monospace"
  readonly property real baseFontSize: Math.max(4, Math.round(height * 0.026))

  visible: pressure > 0.001
  clip: true

  Repeater {
    model: 5

    delegate: Item {
      id: slot
      required property int index

      anchors.fill: parent

      // Randomised afresh every cycle, while the face is invisible.
      property int faceIndex: slot.index % Faces.count()
      property real slotScale: 1.0
      property real originX: 0.5
      property real originY: 0.5

      function reposition() {
        faceIndex = Math.floor(Math.random() * Faces.count())
        slotScale = 0.60 + Math.random() * 0.85
        // Kept off the exact centre so the logo is never fully behind a face.
        originX = 0.08 + Math.random() * 0.84
        originY = 0.10 + Math.random() * 0.72
        riseMs = 320 + Math.random() * 420
        holdMs = 180 + Math.random() * 500
        sinkMs = 380 + Math.random() * 520
      }

      Text {
        id: glyphs
        text: Faces.textAt(slot.faceIndex)
        color: root.faceColor
        font.family: root.fontFamily
        font.pixelSize: root.baseFontSize
        // Sits at a fraction of the layer, then centres itself on that point.
        x: root.width * slot.originX - width / 2
        y: root.height * slot.originY - height / 2
        opacity: slot.presence * root.pressure
        // Swelling slightly while visible is the "pressing closer" read.
        scale: slot.slotScale * (0.94 + 0.10 * slot.presence)
        transformOrigin: Item.Center
        renderType: Text.QtRendering
      }

      // 0..1 presence for this slot alone; the layer's pressure multiplies it.
      property real presence: 0

      // Per-cycle timings, randomised by reposition() while the animation is
      // stopped. They must never be written while it is running: changing a
      // duration inside a running SequentialAnimation restarts the group,
      // which re-fires the script that changed it, which restarts it again.
      // A ScriptAction that retimes its own animation hangs the engine on
      // creation, synchronously, with no error.
      property int riseMs: 400
      property int holdMs: 300
      property int sinkMs: 500

      // The beat owns the rhythm; the animation owns one appearance. Timer
      // intervals are safe to rewrite at any point, animation durations are
      // not, so all the jitter lives here.
      Timer {
        id: beat
        running: root.active
        repeat: false
        interval: 400
        onTriggered: {
          slot.reposition()
          apparition.restart()
        }
      }

      SequentialAnimation {
        id: apparition

        NumberAnimation {
          target: slot; property: "presence"
          to: root.peakOpacity
          duration: slot.riseMs
          easing.type: Easing.OutQuad
        }
        PauseAnimation { duration: slot.holdMs }
        NumberAnimation {
          target: slot; property: "presence"
          to: 0
          duration: slot.sinkMs
          easing.type: Easing.InQuad
        }
        // Queue the next appearance. Only the timer is touched here, so
        // nothing reaches back into the animation that is finishing.
        ScriptAction {
          script: {
            beat.interval = 220 + Math.random() * 1500
            if (root.active) beat.restart()
          }
        }
      }

      Connections {
        target: root
        function onActiveChanged() {
          if (root.active) return
          apparition.stop()
          slot.presence = 0
        }
      }

      // Stagger the pool on startup so the first wave does not arrive as a
      // single synchronised bloom.
      Component.onCompleted: {
        reposition()
        beat.interval = 80 + slot.index * 260 + Math.random() * 300
      }
    }
  }
}
