import QtQuick
import QtTest
import "../../"

// The takeover's one obligation: always hand over.
//
// It sits on top of the lock view holding a still of the desktop. If any path
// through it fails to reach done(), that still stays there for the length of
// the lock -- no wall, no countdown, and no way out, at the moment it is least
// possible to check. Every failure has to end at `finished`.
TestCase {
  name: "Takeover"
  when: windowShown

  Component {
    id: takeoverFactory
    TakeoverView { width: 200; height: 120 }
  }

  SignalSpy { id: spy }

  function make(props) {
    var view = takeoverFactory.createObject(null, props || ({}))
    spy.clear()
    spy.target = view
    spy.signalName = "finished"
    return view
  }

  function test_no_source_hands_over_at_once() {
    // Nothing to tear. Holding a blank screen for the full duration would be
    // the worst of both.
    var view = make({ source: "", durationMs: 5000 })
    compare(view.failed, true)
    view.begin()
    compare(spy.count, 1)
    compare(view.running, false)
    view.destroy()
  }

  function test_a_still_that_does_not_exist_hands_over() {
    var view = make({ source: "file:///nonexistent/nope.png", durationMs: 5000 })
    view.begin()
    spy.wait(3000)
    compare(spy.count, 1)
    compare(view.running, false)
    view.destroy()
  }

  function test_a_healthy_run_finishes_on_its_own_clock() {
    // And not on the hard stop, which sits durationMs + 1500 away. If this
    // ever passed only because the watchdog fired, the sequence would have
    // silently stopped animating and nobody would know.
    var view = make({ source: Qt.resolvedUrl("fixture-still.png"),
                      durationMs: 250 })
    compare(view.failed, false)
    view.begin()
    var began = Date.now()
    spy.wait(2000)
    var took = Date.now() - began
    compare(spy.count, 1)
    compare(view.progress, 1)
    // Comfortably inside the hard stop at 250 + 1500.
    verify(took < 1200)
    view.destroy()
  }

  function test_the_still_actually_loads() {
    var view = make({ source: Qt.resolvedUrl("fixture-still.png") })
    tryCompare(view, "ready", true, 2000)
    compare(view.failed, false)
    view.destroy()
  }

  function test_done_is_idempotent() {
    // Both the sweep finishing and the hard stop firing can reach it, and one
    // must not undo or re-signal the other.
    var view = make({ source: "" })
    view.begin()
    var after = spy.count
    view.done()
    view.done()
    compare(spy.count, after)
    view.destroy()
  }

  function test_it_draws_nothing_until_there_is_something_to_draw() {
    // Fails open: while the still is not ready the lock view underneath is
    // simply visible, rather than being covered by an empty layer.
    var view = make({ source: "" })
    compare(view.visible, false)
    view.destroy()
  }

  function test_beginning_again_mid_run_does_not_restart_it() {
    // Asserting the signal count here catches nothing: restarting an
    // animation does not emit `finished` for the run it abandoned, so a
    // component with no guard at all still signals exactly once. Checked by
    // removing the guard and watching this test keep passing.
    //
    // The observable that does move is the progress. Without the guard a
    // second begin() winds the sequence back to zero and the tear visibly
    // jumps back to the start.
    var view = make({ source: Qt.resolvedUrl("fixture-still.png"),
                      durationMs: 1200 })
    view.begin()
    tryVerify(function () { return view.progress > 0.4 }, 3000)
    var reached = view.progress
    view.begin()
    verify(view.progress >= reached)
    view.destroy()
  }
}
