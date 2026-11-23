package poqi.qcast

import quantum.algorithm.OnlineAlgorithm
import quantum.algorithm.PickedPath
import quantum.topo.Link
import quantum.topo.Node
import quantum.topo.Topo
import quantum.topo.edges
import java.io.StringWriter
import java.util.Base64
import kotlin.system.exitProcess

/** Headless phase bridge to the pinned, unmodified authors' Q-CAST code.
 *
 * INIT<TAB>base64(Topo config)<TAB>true|false
 * SLOT<TAB>u,v;u,v (unique unordered pairs, or empty)<TAB>channel outcome bits
 * EXIT
 *
 * Each response is a flushed JSON line. The caller owns demand multiplicity,
 * physical opportunity identities, elapsed time and useful-request accounting.
 * Current-slot outcome bits are applied only AFTER P2 has chosen its allocation.
 * Swaps are restricted to q=1; the original display RNG draws are overwritten.
 * No state survives a completed slot. Graphs and request sizes are bounded.
 */
object SlotBridge {
    private const val REVISION = "0a0251dd5f38eb1669ff6abe18ab83436ddbba18"

    private fun quote(value: String): String = "\"" + value.map { c ->
        when (c) {
            '\\' -> "\\\\"
            '"' -> "\\\""
            '\n' -> "\\n"
            '\r' -> "\\r"
            '\t' -> "\\t"
            else -> if (c.toInt() < 32) "\\u%04x".format(c.toInt()) else c.toString()
        }
    }.joinToString("") + "\""

    private fun json(value: Any?): String = when (value) {
        null -> "null"
        is String -> quote(value)
        is Double -> { check(value.isFinite()); value.toString() }
        is Float -> { check(value.isFinite()); value.toString() }
        is Number, is Boolean -> value.toString()
        is Map<*, *> -> value.entries.joinToString(",", "{", "}") { quote(it.key.toString()) + ":" + json(it.value) }
        is Iterable<*> -> value.joinToString(",", "[", "]") { json(it) }
        else -> error("Unsupported JSON value: ${value.javaClass}")
    }

    private fun emit(value: Any) {
        println(json(value))
        System.out.flush()
    }

    private fun pathRecord(path: PickedPath): Map<String, Any> = linkedMapOf(
        "score" to path.first, "width" to path.second, "nodes" to path.third.map { it.id })

    private fun create(config: String): Topo {
        check(config.length <= 32000) { "Topology configuration too large" }
        val lines = config.trim().lines().filter { it.isNotBlank() }
        check(lines.size >= 7)
        val n = lines[0].toInt()
        check(n in 2..16) { "Bridge supports 2..16 nodes" }
        check(lines.size > 4 + n)
        check(lines[1].toDouble().isFinite() && lines[1].toDouble() >= 0.0)
        check(lines[2].toDouble() == 1.0) { "Bridge requires deterministic q=1 swaps" }
        check(lines[3].toInt() in 0..16)
        lines.subList(4, 4 + n).forEach { line ->
            val values = line.split(" ")
            check(values.size == 3 && values[0].toInt() in 0..64)
            check(values.drop(1).all { it.toDouble().isFinite() })
        }
        var totalChannels = 0
        val seenEdges = mutableSetOf<Pair<Int, Int>>()
        lines.drop(4 + n).forEach { line ->
            val values = line.split(" ").map { it.toInt() }
            check(values.size == 3)
            val (u, v, channels) = values
            check(u in 0 until n && v in 0 until n && u < v && channels in 1..16)
            check(seenEdges.add(u to v)) { "Repeated physical edge" }
            totalChannels += channels
        }
        check(totalChannels in 1..128) { "Bridge supports at most 128 channels" }
        val topo = Topo(config)
        check(topo.links.all { it.l > 0.0 && it.l.isFinite() && it.p in 0.0..1.0 })
        check(topo.isClean())
        return topo
    }

    private fun resourceCheck(topo: Topo, algorithm: OnlineAlgorithm) {
        val claims = mutableMapOf<Pair<Int, Int>, Int>()
        (algorithm.majorPaths + algorithm.majorPaths.flatMap { algorithm.recoveryPaths[it]!! }).forEach { path ->
            check(path.second > 0 && path.third.distinct().size == path.third.size)
            path.third.edges().forEach { edge ->
                val key = minOf(edge.n1.id, edge.n2.id) to maxOf(edge.n1.id, edge.n2.id)
                claims[key] = (claims[key] ?: 0) + path.second
            }
        }
        topo.links.groupBy { it.n1.id to it.n2.id }.forEach { (edge, links) ->
            check(links.count { it.assigned } == (claims[edge] ?: 0)) { "Channel allocation is not exclusive" }
        }
        topo.nodes.forEach { node ->
            val occupied = node.links.count { it.assigned }
            check(occupied in 0..node.nQubits)
            check(node.nQubits - node.remainingQubits == occupied) { "Physical qubit debit mismatch" }
            val inputs = node.internalLinks.flatMap { listOf(it.first.id, it.second.id) }
            check(inputs.distinct().size == inputs.size) { "Successful swap reused an input" }
            node.internalLinks.forEach { (left, right) ->
                check(left != right && left.contains(node) && right.contains(node))
                check(left.assigned && right.assigned && left.entangled && right.entangled)
                check(left.swappedAt(node) && right.swappedAt(node))
            }
            check(node.links.count { it.swappedAt(node) } == 2 * node.internalLinks.size) {
                "At q=1 every consumed input must belong to a successful swap"
            }
        }
    }

    /** Actual endpoint-valid ebits, retaining physical channel identities.
     * The author counter can report a traversed prefix ending at a swapped
     * destination as an ebit. Such prefixes are diagnostic author counts only.
     */
    private fun physicalPaths(topo: Topo, source: Node, destination: Node): List<List<Int>> {
        val result = mutableListOf<List<Int>>()
        fun walk(current: Node, incoming: Link?, channels: List<Int>, visited: Set<Int>) {
            check(current.id !in visited) { "Cycle in established entanglement" }
            if (current == destination) {
                check(incoming != null)
                if (!incoming.swappedAt(current)) result.add(channels)
                return
            }
            val outgoing = if (incoming == null) current.links.filter { it.entangled && !it.swappedAt(current) }
            else current.internalLinks.filter { it.first == incoming || it.second == incoming }
                .map { if (it.first == incoming) it.second else it.first }
            check(incoming == null || outgoing.size <= 1)
            outgoing.forEach { link ->
                val local = topo.links.indexOf(link)
                check(local >= 0 && local !in channels && link.assigned && link.entangled)
                walk(link.theOtherEndOf(current), link, channels + local, visited + current.id)
            }
        }
        walk(source, null, emptyList(), emptySet())
        check(result.distinct().size == result.size)
        return result
    }

    private fun slot(topo: Topo, algorithm: OnlineAlgorithm, requestText: String, bits: String): Map<String, Any> {
        check(topo.isClean() && topo.links.all { !it.utilized })
        check(bits.length == topo.links.size && bits.all { it == '0' || it == '1' }) { "Invalid channel outcomes" }
        val pairs = if (requestText.isEmpty()) emptyList() else requestText.split(';').map { token ->
            val values = token.split(',').map { it.toInt() }
            check(values.size == 2)
            val (source, destination) = values
            check(source in topo.nodes.indices && destination in topo.nodes.indices && source < destination)
            source to destination
        }
        check(pairs.distinct().size == pairs.size) { "Native demands must be unique unordered pairs" }
        check(pairs.size <= topo.nodes.size * (topo.nodes.size - 1) / 2)
        algorithm.logWriter = StringWriter().buffered()
        algorithm.srcDstPairs.clear()
        algorithm.srcDstPairs.addAll(pairs.map { topo.nodes[it.first] to topo.nodes[it.second] })
        algorithm.P2()
        resourceCheck(topo, algorithm)
        val assigned = topo.links.indices.filter { topo.links[it].assigned }
        val occupancy = topo.nodes.map { it.nQubits - it.remainingQubits }
        val mainPaths = algorithm.majorPaths.map { pathRecord(it) }
        val recoveryPaths = algorithm.majorPaths.flatMap { major -> algorithm.recoveryPaths[major]!!.map { recovery ->
            linkedMapOf("major" to major.third.map { it.id }, "path" to pathRecord(recovery)) } }

        // This is the only point at which the input outcomes are revealed.
        topo.links.forEachIndexed { i, link -> link.entangled = link.assigned && bits[i] == '1' }
        val successful = topo.links.indices.filter { topo.links[it].entangled }
        algorithm.P4()
        resourceCheck(topo, algorithm)
        val physical = pairs.map { physicalPaths(topo, topo.nodes[it.first], topo.nodes[it.second]) }
        val used = physical.flatten().flatten()
        check(used.distinct().size == used.size) { "Physical channels reused by delivered ebits" }
        val authorCounts = pairs.map { topo.getEstablishedEntanglements(topo.nodes[it.first], topo.nodes[it.second]).size }
        val delivered = pairs.indices.map { i -> linkedMapOf(
            "pair" to listOf(pairs[i].first, pairs[i].second), "count" to physical[i].size,
            "paths" to physical[i], "author_count" to authorCounts[i]) }
        val swaps = topo.nodes.sumBy { it.internalLinks.size }
        val allPairs = (0 until topo.nodes.size).flatMap { source ->
            (source + 1 until topo.nodes.size).map { destination ->
                val paths = physicalPaths(topo, topo.nodes[source], topo.nodes[destination])
                linkedMapOf("pair" to listOf(source, destination), "count" to paths.size, "paths" to paths)
            }
        }
        val allPhysicalPaths = (0 until topo.nodes.size).flatMap { source ->
            (source + 1 until topo.nodes.size).flatMap { destination ->
                physicalPaths(topo, topo.nodes[source], topo.nodes[destination])
            }
        }
        val allUsedChannels = allPhysicalPaths.flatten()
        check(allUsedChannels.distinct().size == allUsedChannels.size) { "Final physical pairs share a channel" }
        check(allUsedChannels.sorted() == successful.sorted()) { "Final physical inventory contains a cycle or an unaccounted channel" }
        check(allPhysicalPaths.size == successful.size - swaps) { "Physical pair conservation failed" }
        val post = topo.links.mapIndexed { i, link -> linkedMapOf(
            "channel" to i, "s1" to link.s1, "s2" to link.s2, "utilized" to link.utilized) }
        val swapInputs = topo.nodes.flatMap { node -> node.internalLinks.map { (left, right) ->
            linkedMapOf("node" to node.id, "channels" to listOf(topo.links.indexOf(left), topo.links.indexOf(right))) } }
        val recoveryUse = algorithm.majorPaths.flatMap { algorithm.pathToRecoveryPaths[it].map { recovery ->
            linkedMapOf("nodes" to recovery.path.map { it.id }, "width" to recovery.width,
                "available" to recovery.available, "taken" to recovery.taken) } }
        val outcome = linkedMapOf<String, Any>(
            "assigned" to assigned, "successful" to successful, "swaps" to swaps,
            "delivered" to delivered, "author_counts" to authorCounts,
            "author_accounting_discrepancy" to pairs.indices.any { physical[it].size != authorCounts[it] },
            "major_paths" to mainPaths, "recovery_paths" to recoveryPaths,
            "recovery_use" to recoveryUse, "occupancy" to occupancy,
            "remaining_pairs_before_service" to successful.size - swaps,
            "total_remaining_pairs" to allPhysicalPaths.size, "all_pairs" to allPairs,
            "post_p4_channels" to post, "successful_swap_inputs" to swapInputs)
        check(successful.size - swaps >= physical.sumBy { it.size })
        topo.clearEntanglements()
        check(topo.isClean() && topo.links.all { !it.utilized })
        outcome["reset_clean"] = true
        return outcome
    }

    @JvmStatic fun main(args: Array<String>) {
        check(args.isEmpty()) { "SlotBridge uses the stdin protocol, with no command arguments" }
        var topo: Topo? = null
        var algorithm: OnlineAlgorithm? = null
        var slots = 0
        val reader = System.`in`.bufferedReader(Charsets.UTF_8)
        while (true) {
            val line = reader.readLine() ?: return
            try {
                check(line.length <= 50000) { "Protocol command too large" }
                val parts = line.split('\t')
                when (parts[0]) {
                    "INIT" -> {
                        check(parts.size == 3 && parts[2] in listOf("true", "false"))
                        val currentTopo = create(String(Base64.getDecoder().decode(parts[1]), Charsets.UTF_8))
                        val currentAlgorithm = OnlineAlgorithm(currentTopo, parts[2].toBoolean())
                        topo = currentTopo
                        algorithm = currentAlgorithm
                        currentAlgorithm.prepare()
                        slots = 0
                        emit(linkedMapOf("ready" to true, "source_commit" to REVISION,
                            "q" to currentTopo.q,
                            "channels" to currentTopo.links.mapIndexed { i, link -> linkedMapOf(
                                "id" to i, "edge" to listOf(link.n1.id, link.n2.id), "p" to link.p) },
                            "memory" to currentTopo.nodes.map { it.nQubits }))
                    }
                    "SLOT" -> {
                        check(parts.size == 3)
                        val currentTopo = checkNotNull(topo) { "INIT required before SLOT" }
                        val currentAlgorithm = checkNotNull(algorithm) { "INIT required before SLOT" }
                        check(++slots <= 100000) { "Slot bound exceeded; initialize a new bounded run" }
                        emit(slot(currentTopo, currentAlgorithm, parts[1], parts[2]))
                    }
                    "EXIT" -> { check(parts.size == 1); return }
                    else -> error("Unknown command")
                }
            } catch (error: Throwable) {
                emit(linkedMapOf("error" to (error.message ?: error.javaClass.simpleName)))
                error.printStackTrace(System.err)
                exitProcess(2)
            }
        }
    }
}
