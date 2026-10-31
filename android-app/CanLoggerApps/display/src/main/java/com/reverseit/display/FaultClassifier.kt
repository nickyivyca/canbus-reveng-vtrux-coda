package com.reverseit.display

/**
 * Classifies a Vtrux HV fault from steady-state signals -- no edge capture.
 *
 * The problem this replaces: the previous fault word evaluated a priority
 * ladder against the current sample, and `bcm_epo` is the only condition still
 * true once the contactors have opened. So every fault mode -- isolation,
 * interlock, precharge abort, mid-charge trip -- displayed as `FAULT: EPO`,
 * naming the consequence rather than the cause. Meanwhile a normal EVSE unplug
 * produced the full EPO signature and displayed a red `FAULT: INTERLOCK`.
 *
 * What makes a stateless classifier possible is that the discriminating
 * signals stay true for the whole latched window, not just the 146-200 ms the
 * transition takes. Measured across six captures (see
 * `projects/vtrux/notes/artifacts/fault-display-screenshots/README.md`):
 *
 * | capture | epo | hvil after | gfd after | real fault |
 * |---|---|---|---|---|
 * | normal key-off      | never asserts | 0 | 1000   | no  |
 * | isolation test      | 1 | **1** | **0**    | yes |
 * | interlock test      | 1 | 0     | 1000     | yes |
 * | charge trip         | 1 | 0     | 1023.5   | yes |
 * | operator unplug     | 1 | 0     | 1000     | **no** |
 * | precharge abort     | 1 | **1** | 1023.5   | yes |
 *
 * gfd falls *only* in the isolation case (an earlier assumption that any trip
 * drops it, because HV goes away, is falsified above), and a normal key-off
 * never asserts EPO at all. The one case EPO cannot separate -- operator
 * unplug -- is separated by the BMS's own fault-record annunciator on 0x460,
 * which pushes `F0 00 00` at every real trip and nothing at all at a key-off
 * or an unplug.
 */

/** Signals this classifier reads, resolved out of the flat display map. */
data class FaultEvidence(
    val epo: Boolean,
    val hvilClosed: Boolean,
    val gfd: Double?,
    val contactorState: Int?,
    /** BMS alarm level, 0-3 (0x410 B1 bits 6-7). */
    val alarm: Int,
    /** This trip's 0x460 records, newest first, as "F0 00 00". See [liveRecords]. */
    val records: List<String>,
)

enum class FaultSeverity { NONE, WARNING, FAULT }

data class FaultVerdict(
    val severity: FaultSeverity,
    /** Plain-language cause, e.g. "Interlock opened". */
    val headline: String,
    /** One-line consequence in non-specialist words. */
    val detail: String,
    /** Label/value rows a remote diagnoser would ask for. */
    val evidence: List<Pair<String, String>>,
    /** Raw records, for reading down a phone. */
    val codes: List<String>,
)

/**
 * The universal fault-trip record. Measured present at every real trip and
 * absent at both non-faults that still assert EPO. This is the
 * "not a regular shutdown" gate.
 */
private const val RECORD_FAULT_TRIP = "F0 00 00"

/**
 * A named record. [specificity] exists because the BMS pushes family generics
 * alongside the subcode -- a welded-contactor trip pushes `F6 C0 01` and
 * `F6 C3 02` within the same 50 ms -- so the vaguer of the two must not win
 * just by appearing first.
 */
private data class NamedRecord(
    val headline: String,
    val detail: String,
    val specificity: Int,
)

/** Catalog from `projects/vtrux/notes/battery-fault-codes.md`. */
private val NAMED_RECORDS: Map<String, NamedRecord> = mapOf(
    "F6 CF 00" to NamedRecord("Interlock opened",
        "A high-voltage cover or connector came loose while the pack was live.", 10),
    "F6 C3 02" to NamedRecord("Contactor welded",
        "The battery's main negative contactor did not open when commanded.", 10),
    "F6 C5 03" to NamedRecord("Precharge contactor failed",
        "The pack could not safely bring the high-voltage bus up.", 10),
    "F0 E0 00" to NamedRecord("Precharge failed",
        "The pack tried to connect and stopped partway.", 10),
    "FC 22 02" to NamedRecord("Battery stopped the charge",
        "The pack ended charging on its own.", 10),
    "FC 16 F2" to NamedRecord("Generator inverter not responding",
        "The battery cannot hear the generator inverter.", 10),
    "F6 C0 01" to NamedRecord("Contactor fault",
        "The battery aborted while closing its contactors.", 5),
)

/**
 * `bcm_gfd` is not a continuous measurement, despite its 12-bit field and 0.25
 * scale. Across the twelve fault captures it takes exactly three values and
 * nothing else -- raw 0x000, 0xFA0 and 0xFFE -- and its four MSBs are 0xF
 * whenever it is non-zero:
 *
 *   1000.00  measured, isolation OK
 *      0.00  measured, isolation failed
 *   1023.50  no measurement available
 *
 * The third value is not a healthy reading, which is what the wording below
 * turns on. It shows up whenever the HV bus is down, *and* for a bounded
 * settling window after the contactors close, before the monitor has its first
 * result. Over the corpus, 68 contactors-closed -> 1000.00 transitions:
 * **min 0.96 s, median 15.83 s, max 20.93 s**, with 43 of 68 falling in 10-20 s.
 * That window is why 1023.50 also appears while the contactors read closed
 * (58.6 s of it in state 11 across the captures), which is what ruled out the
 * simpler "the HV bus is down" reading.
 *
 * Measured by `projects/vtrux/notes/artifacts/gfd_value_census.py`.
 */
private const val GFD_NO_READING = 1023.0
private const val GFD_FAULT_BELOW = 500.0

private val NO_FAULT = FaultVerdict(FaultSeverity.NONE, "", "", emptyList(), emptyList())

/** Names of the 0x460 record slots, in page order. */
val FAULT_RECORD_SIGNALS: List<String> = (1..4).flatMap {
    listOf("fr_p${it}_r1", "fr_p${it}_r2")
}

/**
 * The records belonging to *this* trip, read out of the page-0 header rather
 * than out of whatever the record pages last happened to say.
 *
 * Two separate problems make the raw `fr_pN_rM` signals unusable on their own.
 *
 * **The pages go quiet.** 0x460 pages 1-4 are only transmitted while they hold
 * something, so the moment the pack empties its store the pages simply stop --
 * and a display that keeps last-known values per signal goes on reporting what
 * they last said. Measured on `07-charge-trip-hvil` and `12-drive-trip-ac1001`:
 * the header zeroed and page 1 kept its `F0 00 00` for **5.5-5.6 s**. Worse,
 * when the store shrinks from several pages to one the orphaned pages never
 * transmit again -- in `vtrux_20260802_123318` page 2 stopped with `F0 00 00`
 * in it and stayed silent for the remaining ~45 min of the session (0 frames,
 * `fr_pages` pinned at 1 across 22,479 headers). Either case would make a
 * later, innocent EPO read as a hard fault.
 *
 * **The store mixes eras.** Records pushed while EPO was clear stay put when a
 * trip pushes new ones on top. In `05-interlock-fault-drive` the trip's own two
 * records land in front of `FC 16 F2`, pushed 18 s *earlier* -- and `FC 16 F2`
 * is a named code, so a classifier reading the whole list would announce
 * "generator inverter not responding" for an interlock trip.
 *
 * The header fixes both. `fr_grp3`, `fr_grp2` and `fr_grp1` partition the store
 * into three groups summing to `fr_total`, and the slots are laid out in that
 * order -- `fr_grp1` first. The trip's own records are the `fr_grp1` group.
 * Checked by `projects/vtrux/notes/artifacts/fault_record_ordering.py` across
 * all 707 corpus logs that carry 0x460 record pages: the sum invariant and
 * `fr_pages == ceil(fr_total/2)` held on **1,463,537** header samples, and
 * `F0 00 00`, whenever stored, sat inside the first `fr_grp1` slots on all
 * **3,447** samples where it was present. Zero violations of either.
 *
 * Header absent (we have never heard 0x460) yields an empty list, which closes
 * the fault gate. That is deliberate: without the annunciator this classifier
 * cannot tell a fault from a key-off, and it should not guess.
 */
private fun liveRecords(signals: Map<String, Double>): List<String> {
    val pages = signals["fr_pages"]?.toInt() ?: return emptyList()
    if (pages <= 0) return emptyList()
    val group = signals["fr_grp1"]?.toInt() ?: return emptyList()
    if (group <= 0) return emptyList()

    val take = minOf(group, pages * 2, FAULT_RECORD_SIGNALS.size)
    return FAULT_RECORD_SIGNALS.take(take).mapNotNull { name ->
        val raw = signals[name]?.toLong() ?: return@mapNotNull null
        if (raw == 0L) null else formatRecord(raw)
    }.distinct()
}

/** Pull the classifier's inputs out of the flat signal map. */
fun faultEvidenceFrom(signals: Map<String, Double>): FaultEvidence = FaultEvidence(
    epo = signals["bcm_epo"]?.toInt() == 1,
    // Absent means we have never heard the BMS. Treating that as "closed"
    // keeps a missing bus from inventing an interlock fault; the absence
    // itself is a separate problem the strip does not claim to cover.
    hvilClosed = (signals["bcm_hvil_mon"]?.toInt() ?: 1) == 1,
    gfd = signals["bcm_gfd"],
    contactorState = signals["bcm_mainc_stat"]?.toInt(),
    alarm = signals["bcm_alarm"]?.toInt() ?: 0,
    records = liveRecords(signals),
)

/** 24-bit record value to the "F0 00 00" form used in the code catalog. */
private fun formatRecord(raw: Long): String {
    val b0 = (raw shr 16) and 0xFF
    val b1 = (raw shr 8) and 0xFF
    val b2 = raw and 0xFF
    return "%02X %02X %02X".format(b0, b1, b2)
}

/**
 * The tier below a fault: the pack is still running, but it has raised an
 * alarm. Only level 1 qualifies, and only while the contactors are closed.
 *
 * Level 1 earns a place on screen because it leads the trip rather than
 * accompanying it. Measured over ~2 h of `logs/actual-failed-charges`
 * (`truklog_M0_*`, `truklog_M1_*`): `bcm_alarm` sat at 0 for every second of
 * every file except the two containing the failure, where it went to 1 and
 * held for **10.2 s** and **10.3 s** respectively, with EPO rising at the exact
 * instant the level-1 span ended. No other level-1 span anywhere in the set.
 *
 * Levels 2 and 3 are excluded. Level 2 is the resting value through healthy
 * driving and charging in the 2026 captures (46 s of 55 s in
 * `01-healthy-drive`, all 60 s of `03-healthy-charge`), and level 3 rides along
 * with trips the fault tier already names -- including the operator unplug,
 * which is not a fault at all.
 *
 * The closed-contactor gate is a deliberate restriction rather than a fix for
 * an observed false alarm: a warning is only worth the driver's attention
 * while the high-voltage system is actually live.
 *
 * Deliberately unnamed beyond "warning" -- `bcm_alarm` is a bare 2-bit level
 * (`NONE`/`TYPE1`/`TYPE2`/`TYPE3`) and this project has not established what
 * the levels mean.
 */
private fun warningOrNone(e: FaultEvidence): FaultVerdict {
    if (e.alarm != 1 || e.contactorState !in setOf(11, 12)) return NO_FAULT
    return FaultVerdict(
        FaultSeverity.WARNING,
        "Battery warning",
        "The pack has raised an alarm. It is still running -- this often comes "
            + "before it stops on its own.",
        listOf(
            "Alarm level" to "${e.alarm}",
            "Contactors" to contactorWord(e.contactorState),
        ),
        emptyList(),
    )
}

fun classify(e: FaultEvidence): FaultVerdict {
    // A normal key-off never asserts EPO.
    if (!e.epo) return warningOrNone(e)

    // EPO with no trip record is an operator action. Pulling the charge
    // handle mid-charge produces EPO + TYPE3 + ALL_OPEN_SHUTDOWN and pushes
    // no records at all.
    //
    // The record store is scoped to the current EPO episode without any help
    // from us: measured on captures 06, 07, 08, 12 and
    // `vtrux_20260802_123318_T0` (twice), every counter in the page-0 header
    // drops to zero within ~10 ms of EPO deasserting, and the store then
    // refills from live pushes. So a record standing while EPO is asserted
    // belongs to *this* trip. What that does not survive on its own is the
    // record pages going quiet after the clear -- see [liveRecords].
    if (RECORD_FAULT_TRIP !in e.records) return warningOrNone(e)

    val evidence = listOf(
        "Interlock loop" to if (e.hvilClosed) "closed" else "OPEN",
        "Isolation" to when {
            e.gfd == null -> "no reading"
            e.gfd < GFD_FAULT_BELOW -> "FAILED (${"%.0f".format(e.gfd)})"
            e.gfd >= GFD_NO_READING -> "no reading"
            else -> "ok (${"%.0f".format(e.gfd)})"
        },
        "Contactors" to contactorWord(e.contactorState),
    )

    // A named record beats inference -- it is the pack's own vocabulary.
    NAMED_RECORDS.entries
        .filter { it.key in e.records }
        .maxByOrNull { it.value.specificity }
        ?.let { (_, named) ->
            return FaultVerdict(
                FaultSeverity.FAULT, named.headline, named.detail, evidence, e.records,
            )
        }

    // Otherwise fall back to the signals that stay true while latched.
    // Isolation first: it is the only fault that pulls gfd down, and it
    // leaves the interlock loop closed.
    if (e.gfd != null && e.gfd < GFD_FAULT_BELOW) {
        return FaultVerdict(
            FaultSeverity.FAULT,
            "Isolation fault",
            "The pack detected high voltage leaking to the truck body.",
            evidence, e.records,
        )
    }
    if (!e.hvilClosed) {
        return FaultVerdict(
            FaultSeverity.FAULT,
            "Interlock opened",
            "A high-voltage cover or connector came loose while the pack was live.",
            evidence, e.records,
        )
    }
    return FaultVerdict(
        FaultSeverity.FAULT,
        "Battery fault",
        "The pack shut the high-voltage system down and did not say why.",
        evidence, e.records,
    )
}

private fun contactorWord(state: Int?): String = when (state) {
    null -> "no reading"
    0, 14 -> "open"
    11 -> "closed (drive)"
    12 -> "closed (charge)"
    13 -> "opening"
    else -> "state $state"
}
