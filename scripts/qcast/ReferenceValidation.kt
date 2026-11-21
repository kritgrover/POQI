package poqi.qcast

import quantum.algorithm.OnlineAlgorithm
import quantum.algorithm.PickedPath
import quantum.randGen
import quantum.topo.Link
import quantum.topo.Node
import quantum.topo.Topo
import quantum.topo.edges
import java.io.File
import java.io.StringWriter
import kotlin.math.abs
import kotlin.math.ln

/** Bounded headless probes of the unmodified authors' implementation.
 * Controlled fixtures replace P3 link outcomes after P2, and can replace q for
 * P4. They validate decisions/accounting, not a stochastic experiment. P2 itself
 * consumes display-only generation draws in the authors' implementation.
 */
object ReferenceValidation {
    private fun json(value: Any?): String = when (value) {
        null -> "null"
        is String -> "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"")
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\""
        is Number, is Boolean -> value.toString()
        is Map<*, *> -> value.entries.joinToString(",", "{", "}") { json(it.key.toString()) + ":" + json(it.value) }
        is Iterable<*> -> value.joinToString(",", "[", "]") { json(it) }
        else -> error("Unsupported JSON value: ${value.javaClass}")
    }

    private fun topology(memory: List<Int>, edges: List<Triple<Int, Int, Int>>,
                         q: Double = 1.0, alpha: Double = 0.0, k: Int = 0,
                         locations: List<Pair<Double, Double>> = memory.indices.map { it.toDouble() to 0.0 }): Topo {
        return Topo((listOf(memory.size.toString(), alpha.toString(), q.toString(), k.toString()) +
            memory.indices.map { "${memory[it]} ${locations[it].first} ${locations[it].second}" } +
            edges.map { "${it.first} ${it.second} ${it.third}" }).joinToString("\n"))
    }

    private fun pathRecord(p: PickedPath): Map<String, Any> = linkedMapOf(
        "score" to p.first, "width" to p.second, "nodes" to p.third.map { it.id })

    private fun resources(t: Topo, a: OnlineAlgorithm) {
        val claims = mutableMapOf<Pair<Int, Int>, Int>()
        (a.majorPaths + a.majorPaths.flatMap { a.recoveryPaths[it]!! }).forEach { p ->
            check(p.second > 0)
            check(p.third.distinct().size == p.third.size) { "Allocation contains a cycle" }
            p.third.edges().forEach { e ->
                val key = minOf(e.n1.id, e.n2.id) to maxOf(e.n1.id, e.n2.id)
                claims[key] = (claims[key] ?: 0) + p.second
            }
        }
        t.links.groupBy { it.n1.id to it.n2.id }.forEach { (edge, links) ->
            check(links.count { it.assigned } == (claims[edge] ?: 0)) { "Nonexclusive path allocation" }
        }
        t.nodes.forEach { node ->
            val occupied = node.links.count { it.assigned }
            check(occupied <= node.nQubits && node.remainingQubits >= 0)
            check(node.nQubits - node.remainingQubits == occupied) { "Incorrect physical memory debit" }
            val successfulInputs = node.internalLinks.flatMap { listOf(it.first.id, it.second.id) }
            check(successfulInputs.distinct().size == successfulInputs.size) { "Reused successful swap input" }
            node.internalLinks.forEach { (left, right) ->
                check(left != right && left.contains(node) && right.contains(node))
                check(left.assigned && right.assigned && left.entangled && right.entangled)
                check(left.swappedAt(node) && right.swappedAt(node))
            }
            check(node.links.count { it.swappedAt(node) } % 2 == 0)
        }
    }

    // Independent physical-link traversal; preserves lane identities, unlike a
    // list of node paths, so a duplicate counted ebit is detectable.
    private fun physicalDeliveries(t: Topo, source: Node, destination: Node): List<List<Int>> {
        val out = mutableListOf<List<Int>>()
        fun walk(current: Node, incoming: Link?, channelIds: List<Int>, visited: Set<Int>) {
            check(current.id !in visited) { "Cycle in established entanglement" }
            if (current == destination) {
                check(incoming != null && !incoming.swappedAt(current))
                out.add(channelIds)
                return
            }
            val outgoing = if (incoming == null) current.links.filter { it.entangled && !it.swappedAt(current) }
            else current.internalLinks.filter { it.first == incoming || it.second == incoming }
                .map { if (it.first == incoming) it.second else it.first }
            check(incoming == null || outgoing.size <= 1)
            outgoing.forEach { link ->
                check(link.assigned && link.entangled && link.id !in channelIds)
                walk(link.theOtherEndOf(current), link, channelIds + link.id, visited + current.id)
            }
        }
        walk(source, null, emptyList(), emptySet())
        check(out.distinct().size == out.size)
        return out
    }

    private fun reset(t: Topo) {
        t.clearEntanglements()
        check(t.isClean())
        check(t.links.all { !it.utilized })
        check(t.nodes.all { it.remainingQubits == it.nQubits })
    }

    private fun controlled(name: String, t: Topo, requests: List<Pair<Int, Int>>,
                           expected: List<Int>, recovery: Boolean = false,
                           p4q: Double = 1.0, fail: (Link) -> Boolean = { false },
                           allocationCheck: (OnlineAlgorithm) -> Unit = {},
                           outcomeCheck: (OnlineAlgorithm) -> Unit = {}): Map<String, Any> {
        randGen.setSeed(20261120L)
        val config = t.toConfig()
        val a = OnlineAlgorithm(t, recovery)
        val log = StringWriter()
        a.logWriter = log.buffered()
        a.prepare()
        a.srcDstPairs.addAll(requests.map { t.nodes[it.first] to t.nodes[it.second] })
        a.P2()
        resources(t, a)
        allocationCheck(a)
        val allocations = a.majorPaths.map { pathRecord(it) }
        val recoveries = a.majorPaths.flatMap { p -> a.recoveryPaths[p]!!.map {
            linkedMapOf("major" to p.third.map { node -> node.id }, "path" to pathRecord(it)) } }
        val occupancy = t.nodes.map { it.nQubits - it.remainingQubits }
        val remaining = t.nodes.map { it.remainingQubits }
        t.links.forEach { it.entangled = it.assigned && !fail(it) }
        val linkSnapshot = t.links.mapIndexed { i, l -> linkedMapOf(
            "channel" to i, "author_id" to l.id, "edge" to listOf(l.n1.id, l.n2.id), "assigned" to l.assigned,
            "p" to l.p, "success" to l.entangled) }
        val attempted = t.links.count { it.assigned }
        val generated = t.links.count { it.entangled }
        t.q = p4q
        a.P4()
        resources(t, a)
        outcomeCheck(a)
        val counts = a.srcDstPairs.map { (s, d) -> t.getEstablishedEntanglements(s, d).size }
        check(counts == expected) { "$name: expected $expected, observed $counts" }
        val independent = a.srcDstPairs.map { (s, d) -> physicalDeliveries(t, s, d) }
        check(independent.map { it.size } == counts)
        val usedChannels = independent.flatten().flatten()
        check(usedChannels.distinct().size == usedChannels.size) { "A physical ebit serves more than one demand" }
        val swapAttempts = t.links.sumBy { (if (it.s1) 1 else 0) + (if (it.s2) 1 else 0) } / 2
        val successfulSwaps = t.nodes.sumBy { it.internalLinks.size }
        val postP4Channels = t.links.mapIndexed { i, link -> linkedMapOf(
            "channel" to i, "s1" to link.s1, "s2" to link.s2, "utilized" to link.utilized) }
        val successfulSwapInputs = t.nodes.flatMap { node -> node.internalLinks.map { (left, right) ->
            linkedMapOf("node" to node.id, "channels" to listOf(t.links.indexOf(left), t.links.indexOf(right))) } }
        val recoveryUse = a.majorPaths.flatMap { a.pathToRecoveryPaths[it].map { r ->
            linkedMapOf("nodes" to r.path.map { it.id }, "width" to r.width,
                "available" to r.available, "taken" to r.taken) } }
        val deliveries = independent.map { paths -> paths.map { ids -> ids.map { id -> t.links.indexOfFirst { it.id == id } } } }
        reset(t)
        a.logWriter.flush()
        return linkedMapOf("name" to name, "mode" to "controlled_P3_and_P4", "topology" to config,
            "requests" to requests.map { listOf(it.first, it.second) }, "recovery_enabled" to recovery,
            "p4_swap_probability" to p4q, "major_paths" to allocations, "recovery_paths" to recoveries,
            "occupied_qubits_after_P2" to occupancy, "remaining_qubits_after_P2" to remaining,
            "channels" to linkSnapshot,
            "effective_channel_attempts" to attempted, "successful_links" to generated,
            "swap_attempts" to swapAttempts, "successful_swaps" to successfulSwaps,
            "post_p4_channels" to postP4Channels, "successful_swap_inputs" to successfulSwapInputs,
            "ebits_per_pair" to counts, "delivered_ebits" to counts.sum(),
            "served_sd_pairs" to counts.count { it > 0 }, "useful_unit_requests" to counts.count { it > 0 },
            "surplus_ebits_for_one_request_per_pair" to counts.sum() - counts.count { it > 0 },
            "physical_delivery_channels" to deliveries, "recovery_use" to recoveryUse,
            "reset_clean" to true, "author_log" to log.toString())
    }

    @JvmStatic fun main(args: Array<String>) {
        check(args.size == 1) { "Usage: poqi.qcast.ReferenceValidation OUTPUT.json" }
        val cases = mutableListOf<Map<String, Any>>()
        fun direct(memory: List<Int>, channels: Int) = topology(memory, listOf(Triple(0, 1, channels)))
        fun chain(memory: List<Int>, channels: Int = 1) = topology(memory,
            listOf(Triple(0, 1, channels), Triple(1, 2, channels)))
        val end = listOf(0 to 2)
        cases += controlled("direct_unit", direct(listOf(1, 1), 1), listOf(0 to 1), listOf(1))
        cases += controlled("direct_memory_bottleneck", direct(listOf(2, 3), 4), listOf(0 to 1), listOf(2))
        cases += controlled("direct_channel_bottleneck", direct(listOf(3, 3), 1), listOf(0 to 1), listOf(1))
        val partial = direct(listOf(3, 3), 3)
        val failedId = partial.links.first().id
        cases += controlled("direct_partial_link_failure", partial, listOf(0 to 1), listOf(2), fail = { it.id == failedId })
        cases += controlled("direct_no_memory", direct(listOf(0, 1), 1), listOf(0 to 1), listOf(0))
        cases += controlled("chain_success", chain(listOf(1, 2, 1)), end, listOf(1))
        cases += controlled("chain_pivot_memory_blocked", chain(listOf(1, 1, 1)), end, listOf(0))
        cases += controlled("chain_link_failure", chain(listOf(1, 2, 1)), end, listOf(0),
            fail = { it.n1.id == 1 && it.n2.id == 2 })
        cases += controlled("chain_swap_failure", chain(listOf(1, 2, 1)), end, listOf(0), p4q = 0.0)
        cases += controlled("chain_width_two", chain(listOf(2, 4, 2), 2), end, listOf(2))

        val diamondEdges = listOf(Triple(0, 1, 1), Triple(1, 3, 1), Triple(0, 2, 1), Triple(2, 3, 1))
        cases += controlled("diamond_memory_detour", topology(listOf(1, 1, 2, 1), diamondEdges),
            listOf(0 to 3), listOf(1), allocationCheck = { a ->
                check(a.majorPaths.single().third.map { it.id } == listOf(0, 2, 3)) })
        cases += controlled("diamond_competing_requests", topology(listOf(2, 2, 2, 2), diamondEdges, q = 0.8),
            listOf(0 to 3, 0 to 1), listOf(1, 1), allocationCheck = { a ->
                check(a.majorPaths.map { p -> p.third.map { it.id } } == listOf(listOf(0, 1), listOf(0, 2, 3))) })
        cases += controlled("widest_first_counterexample", topology(listOf(2, 4, 2),
            listOf(Triple(0, 1, 2), Triple(1, 2, 2), Triple(0, 2, 1)), q = 0.1),
            end, listOf(2), allocationCheck = { a ->
                val p = a.majorPaths.single()
                check(p.second == 2 && p.third.map { it.id } == listOf(0, 1, 2))
                check(abs(p.first - 0.2) < 1e-12)
                val directScore = a.topo.e(listOf(a.topo.nodes[0], a.topo.nodes[2]), 1, DoubleArray(2))
                check(abs(directScore - 1.0) < 1e-12 && directScore > p.first) })

        fun recoveryTopology() = topology(listOf(1, 4, 4, 1, 2),
            listOf(Triple(0, 1, 1), Triple(1, 2, 1), Triple(2, 3, 1), Triple(1, 4, 1), Triple(2, 4, 1)),
            q = 0.9, k = 1,
            locations = listOf(0.0 to 0.0, 1.0 to 0.0, 2.0 to 0.0, 3.0 to 0.0, 1.5 to 1.0))
        for (enabled in listOf(false, true)) {
            cases += controlled(if (enabled) "recovery_repairs_failed_segment" else "recovery_disabled_failure",
                recoveryTopology(), listOf(0 to 3), listOf(if (enabled) 1 else 0), recovery = enabled,
                fail = { it.n1.id == 1 && it.n2.id == 2 }, allocationCheck = { a ->
                    check(a.majorPaths.single().third.map { it.id } == listOf(0, 1, 2, 3))
                    val r = a.recoveryPaths[a.majorPaths.single()]!!
                    check(r.size == if (enabled) 1 else 0)
                    if (enabled) check(r.single().third.map { it.id } == listOf(1, 4, 2)) },
                outcomeCheck = { a -> if (enabled) check(a.pathToRecoveryPaths[a.majorPaths.single()].single().taken == 1) })
        }
        cases += controlled("recovery_detour_failure", recoveryTopology(), listOf(0 to 3), listOf(0), recovery = true,
            fail = { it.n1.id == 1 && (it.n2.id == 2 || it.n2.id == 4) })

        val metricTopo = topology(listOf(2, 4, 2), listOf(Triple(0, 1, 2), Triple(1, 2, 2)), q = 0.8, alpha = ln(2.0))
        val directMetric = metricTopo.e(metricTopo.nodes.take(2), 2, DoubleArray(3))
        val chainMetric = metricTopo.e(metricTopo.nodes, 2, DoubleArray(3))
        check(abs(directMetric - 1.0) < 1e-12)
        check(abs(chainMetric - 0.5) < 1e-12) // (.75^2 + .25^2) * .8

        fun nativeCounts(): List<List<Int>> {
            randGen.setSeed(20261120L)
            val t = topology(listOf(2, 2), listOf(Triple(0, 1, 2)), alpha = ln(2.0))
            val a = OnlineAlgorithm(t, false)
            a.logWriter = StringWriter().buffered()
            a.prepare()
            return (1..8).map {
                val r = a.work(listOf(t.nodes[0] to t.nodes[1]))
                check(t.isClean() && t.links.all { !it.utilized })
                check(r.first == if (r.second > 0) 1 else 0)
                check(r.second in 0..2)
                listOf(r.first, r.second)
            }
        }
        val seededNative = nativeCounts()
        check(seededNative == nativeCounts())
        val nativeTopo = direct(listOf(2, 2), 2)
        val native = OnlineAlgorithm(nativeTopo, false)
        native.logWriter = StringWriter().buffered()
        native.prepare()
        val nativeResults = (1..2).map {
            val r = native.work(listOf(nativeTopo.nodes[0] to nativeTopo.nodes[1]))
            check(r == (1 to 2) && nativeTopo.isClean() && nativeTopo.links.all { !it.utilized })
            listOf(r.first, r.second)
        }
        val duplicateResult = native.work(listOf(nativeTopo.nodes[0] to nativeTopo.nodes[1],
            nativeTopo.nodes[0] to nativeTopo.nodes[1]))
        check(duplicateResult == (2 to 4) && nativeTopo.isClean())
        val report = linkedMapOf("schema_version" to 1, "source_commit" to "0a0251dd5f38eb1669ff6abe18ab83436ddbba18",
            "D" to 1, "seed" to 20261120L, "controlled_cases" to cases,
            "metric_checks" to linkedMapOf("direct_width2_p_half" to directMetric,
                "chain_width2_p_half_q_point8" to chainMetric),
            "metric_queries" to listOf(
                linkedMapOf("path" to listOf(0, 1), "width" to 2, "link_ps" to listOf(0.5),
                    "q" to 0.8, "score" to directMetric),
                linkedMapOf("path" to listOf(0, 1, 2), "width" to 2, "link_ps" to listOf(0.5, 0.5),
                    "q" to 0.8, "score" to chainMetric)),
            "native_work" to linkedMapOf("deterministic_slots" to nativeResults,
                "seeded_p_half_slots" to seededNative, "repeated_seed_identical" to true,
                "reset_clean_after_every_slot" to true,
                "duplicate_pair_diagnostic" to linkedMapOf("input_pair_entries" to 2,
                    "physical_ebits" to 2, "reported_pair_entries_served" to duplicateResult.first,
                    "reported_ebits" to duplicateResult.second,
                    "interpretation" to "Duplicate SD entries double-count physical ebits; not a unit-request multiset interface")),
            "status" to "passed")
        File(args[0]).writeText(json(report) + "\n")
        println("ReferenceValidation passed: ${cases.size} controlled cases, metric and native-work controls")
    }
}
