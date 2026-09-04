import QtQuick
import QtTest
import "../../"

// The resolver panel's counting rules.
//
// This panel exists to tell apart what the hosts file claims from what the
// resolver actually does, so the failure that matters is it reporting
// confidence it has not got. It shipped doing exactly that once: 121 domains
// were added between two sweeps and it said "all 128 sunk at the resolver" on
// the strength of seven answers, because an unprobed subject was being counted
// as a clear one.
TestCase {
  name: "StationBus"

  Component {
    id: busFactory
    StationBus {}
  }

  function make(domains, results, sweptAt) {
    return busFactory.createObject(null, {
      domains: domains,
      results: results,
      sweptAt: sweptAt === undefined ? 1000 : sweptAt,
      interval: 300,
      epoch: 1000
    })
  }

  // ---- what a subject's state is -----------------------------------------

  function test_a_domain_with_no_answer_is_unknown_not_sunk() {
    var bus = make(["a.com", "b.com"], { "a.com": "sunk" })
    compare(bus.stateOf("a.com"), "sunk")
    compare(bus.stateOf("b.com"), "unknown")
    bus.destroy()
  }

  function test_counts_split_sunk_from_unprobed() {
    var bus = make(["a.com", "b.com", "c.com"], { "a.com": "sunk" })
    compare(bus.sunkCount, 1)
    compare(bus.unknownCount, 2)
    bus.destroy()
  }

  function test_a_leaking_domain_is_neither_sunk_nor_unknown() {
    var bus = make(["a.com"], { "a.com": "leaking" })
    compare(bus.sunkCount, 0)
    compare(bus.unknownCount, 0)
    compare(bus.leaks, ["a.com"])
    bus.destroy()
  }

  function test_unresolved_is_not_counted_as_sunk() {
    // NXDOMAIN means something other than our hosts entry answered. It is not
    // a leak, but it is not our sink either.
    var bus = make(["a.com"], { "a.com": "unresolved" })
    compare(bus.sunkCount, 0)
    compare(bus.leaks.length, 0)
    bus.destroy()
  }

  // ---- the regression ----------------------------------------------------

  function test_a_partial_sweep_never_reads_as_all_clear() {
    // The one that shipped. Seven answers, 128 subjects.
    var domains = []
    var results = ({})
    for (var i = 0; i < 128; i++) domains.push("d" + i + ".com")
    for (var j = 0; j < 7; j++) results["d" + j + ".com"] = "sunk"

    var bus = make(domains, results)
    compare(bus.sunkCount, 7)
    compare(bus.unknownCount, 121)
    verify(bus.sunkCount < bus.domains.length)
    bus.destroy()
  }

  function test_a_complete_sweep_may_say_all_clear() {
    var bus = make(["a.com", "b.com"], { "a.com": "sunk", "b.com": "sunk" })
    compare(bus.unknownCount, 0)
    compare(bus.sunkCount, bus.domains.length)
    bus.destroy()
  }

  function test_never_swept_is_told_apart_from_swept_and_clear() {
    // sweptAt of 0 is "no sweep has run", which must not look like "swept,
    // nothing to report".
    var never = make(["a.com"], ({}), 0)
    compare(never.swept, false)
    var swept = make(["a.com"], { "a.com": "sunk" }, 1000)
    compare(swept.swept, true)
    never.destroy(); swept.destroy()
  }

  // ---- the countdown ------------------------------------------------------

  function test_the_countdown_runs_against_the_daemons_timestamp() {
    var bus = make(["a.com"], { "a.com": "sunk" }, 1000)
    bus.epoch = 1000 + 120
    compare(bus.nextIn, 180)
    bus.destroy()
  }

  function test_an_overdue_sweep_floors_at_zero_rather_than_going_negative() {
    var bus = make(["a.com"], { "a.com": "sunk" }, 1000)
    bus.epoch = 1000 + 5000
    compare(bus.nextIn, 0)
    bus.destroy()
  }

  function test_there_is_no_countdown_before_the_first_sweep() {
    var bus = make(["a.com"], ({}), 0)
    compare(bus.nextIn, -1)
    bus.destroy()
  }

  // ---- nothing to report --------------------------------------------------

  function test_no_subjects_is_not_a_crash() {
    var bus = make([], ({}), 0)
    compare(bus.sunkCount, 0)
    compare(bus.unknownCount, 0)
    compare(bus.leaks.length, 0)
    bus.destroy()
  }

  function test_a_missing_results_object_is_not_a_crash() {
    var bus = make(["a.com"], undefined, 1000)
    compare(bus.stateOf("a.com"), "unknown")
    bus.destroy()
  }
}
