package com.automationui

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class RecordedAction(
    val type: String,
    val packageName: String?,
    val text: String?,
    val viewId: String?,
    val contentDescription: String?,
    val className: String?,
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
    val screenWidth: Int,
    val screenHeight: Int,
    val scrollDeltaY: Int,
    val timestamp: Long,
    val inputValue: String? = null,
    val hintText: String? = null,
    val displayRotation: Int = 0,
    val schemaVersion: Int = 2,
    val gestureKind: String? = null,
    val gestureStartX: Int = -1,
    val gestureStartY: Int = -1,
    val gestureEndX: Int = -1,
    val gestureEndY: Int = -1,
    val gestureDurationMs: Long = 350L,
    val waitDurationMs: Long = 0L,
    val waitTimeoutMs: Long = 15_000L
) {
    fun toJson() = JSONObject().apply {
        put("type", type)
        put("packageName", packageName ?: JSONObject.NULL)
        put("text", text ?: JSONObject.NULL)
        put("viewId", viewId ?: JSONObject.NULL)
        put("contentDescription", contentDescription ?: JSONObject.NULL)
        put("className", className ?: JSONObject.NULL)
        put("left", left); put("top", top); put("right", right); put("bottom", bottom)
        put("screenWidth", screenWidth); put("screenHeight", screenHeight)
        put("scrollDeltaY", scrollDeltaY); put("timestamp", timestamp)
        put("inputValue", inputValue ?: JSONObject.NULL)
        put("hintText", hintText ?: JSONObject.NULL)
        put("displayRotation", displayRotation)
        put("schemaVersion", schemaVersion)
        put("gestureKind", gestureKind ?: JSONObject.NULL)
        put("gestureStartX", gestureStartX)
        put("gestureStartY", gestureStartY)
        put("gestureEndX", gestureEndX)
        put("gestureEndY", gestureEndY)
        put("gestureDurationMs", gestureDurationMs)
        put("waitDurationMs", waitDurationMs)
        put("waitTimeoutMs", waitTimeoutMs)
    }

    companion object {
        fun fromJson(obj: JSONObject) = RecordedAction(
            type = obj.optString("type"),
            packageName = obj.optString("packageName").takeUnless { it == "null" || it.isBlank() },
            text = obj.optString("text").takeUnless { it == "null" },
            viewId = obj.optString("viewId").takeUnless { it == "null" || it.isBlank() },
            contentDescription = obj.optString("contentDescription").takeUnless { it == "null" || it.isBlank() },
            className = obj.optString("className").takeUnless { it == "null" || it.isBlank() },
            left = obj.optInt("left"), top = obj.optInt("top"),
            right = obj.optInt("right"), bottom = obj.optInt("bottom"),
            screenWidth = obj.optInt("screenWidth"), screenHeight = obj.optInt("screenHeight"),
            scrollDeltaY = obj.optInt("scrollDeltaY"), timestamp = obj.optLong("timestamp"),
            inputValue = if (obj.has("inputValue") && !obj.isNull("inputValue")) {
                obj.optString("inputValue")
            } else null,
            hintText = obj.optString("hintText").takeUnless { it == "null" || it.isBlank() },
            displayRotation = obj.optInt("displayRotation", 0),
            schemaVersion = obj.optInt("schemaVersion", 1),
            gestureKind = obj.optString("gestureKind").takeUnless { it == "null" || it.isBlank() },
            gestureStartX = obj.optInt("gestureStartX", -1),
            gestureStartY = obj.optInt("gestureStartY", -1),
            gestureEndX = obj.optInt("gestureEndX", -1),
            gestureEndY = obj.optInt("gestureEndY", -1),
            gestureDurationMs = obj.optLong("gestureDurationMs", 350L),
            waitDurationMs = obj.optLong("waitDurationMs", 0L),
            waitTimeoutMs = obj.optLong("waitTimeoutMs", 15_000L)
        )
    }
}

object WorkflowStore {
    private const val PREFS = "automation_ui"
    private const val KEY_ACTIONS = "actions"
    private const val KEY_RECORDING = "recording"
    private const val KEY_STATUS = "status"
    private const val KEY_RECORD_TEXT = "record_text_input"
    private const val KEY_REPLAY_LOG = "replay_log"

    fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    fun isRecording(context: Context) = prefs(context).getBoolean(KEY_RECORDING, false)
    fun setRecording(context: Context, value: Boolean) { prefs(context).edit().putBoolean(KEY_RECORDING, value).apply() }
    fun isRecordingText(context: Context) = prefs(context).getBoolean(KEY_RECORD_TEXT, false)
    fun setRecordingText(context: Context, value: Boolean) { prefs(context).edit().putBoolean(KEY_RECORD_TEXT, value).apply() }
    fun setStatus(context: Context, value: String) { prefs(context).edit().putString(KEY_STATUS, value).apply() }
    fun status(context: Context) = prefs(context).getString(KEY_STATUS, "Ready") ?: "Ready"

    fun actions(context: Context): MutableList<RecordedAction> {
        val array = runCatching { JSONArray(prefs(context).getString(KEY_ACTIONS, "[]") ?: "[]") }.getOrDefault(JSONArray())
        return MutableList(array.length()) { index -> RecordedAction.fromJson(array.getJSONObject(index)) }
    }

    fun addAction(context: Context, action: RecordedAction) {
        val array = runCatching { JSONArray(prefs(context).getString(KEY_ACTIONS, "[]") ?: "[]") }.getOrDefault(JSONArray())
        if (action.type == "SET_TEXT" && array.length() > 0) {
            val lastIndex = array.length() - 1
            val last = runCatching { RecordedAction.fromJson(array.getJSONObject(lastIndex)) }.getOrNull()
            if (last != null && last.type == "SET_TEXT" && last.packageName == action.packageName &&
                last.viewId == action.viewId &&
                last.left == action.left && last.top == action.top &&
                last.right == action.right && last.bottom == action.bottom &&
                action.timestamp - last.timestamp in 0..1500) {
                array.put(lastIndex, action.toJson())
                prefs(context).edit().putString(KEY_ACTIONS, array.toString()).apply()
                return
            }
        }

        // A single finger swipe can emit several TYPE_VIEW_SCROLLED events.
        // Coalesce near-identical events from the same scroll container so replay
        // performs one scroll rather than repeating the same movement several times.
        if (action.type == "SCROLL" && array.length() > 0) {
            val lastIndex = array.length() - 1
            val last = runCatching { RecordedAction.fromJson(array.getJSONObject(lastIndex)) }.getOrNull()
            val sameDirection = last != null &&
                (last.scrollDeltaY == 0 || action.scrollDeltaY == 0 ||
                    (last.scrollDeltaY > 0 && action.scrollDeltaY > 0) ||
                    (last.scrollDeltaY < 0 && action.scrollDeltaY < 0))
            if (last != null && last.type == "SCROLL" &&
                last.packageName == action.packageName &&
                last.viewId == action.viewId &&
                last.className == action.className &&
                last.left == action.left && last.top == action.top &&
                last.right == action.right && last.bottom == action.bottom &&
                sameDirection && action.timestamp - last.timestamp in 0..350) {
                val maxDelta = action.screenHeight.coerceAtLeast(1) * 2
                val mergedDelta = when {
                    action.scrollDeltaY == 0 -> last.scrollDeltaY
                    last.scrollDeltaY == 0 -> action.scrollDeltaY
                    else -> (last.scrollDeltaY + action.scrollDeltaY).coerceIn(-maxDelta, maxDelta)
                }
                array.put(lastIndex, action.copy(scrollDeltaY = mergedDelta).toJson())
                prefs(context).edit().putString(KEY_ACTIONS, array.toString()).apply()
                return
            }
        }
        if (action.type == "HOME" && array.length() > 0 &&
            runCatching { array.getJSONObject(array.length() - 1).optString("type") }.getOrNull() == "HOME") return
        val existing = (0 until array.length()).map { RecordedAction.fromJson(array.getJSONObject(it)) }
        val normalized = insertRecordedWaits(existing + action)
        val output = JSONArray().apply { normalized.forEach { put(it.toJson()) } }
        prefs(context).edit().putString(KEY_ACTIONS, output.toString()).apply()
    }

    fun insertActionAt(context: Context, action: RecordedAction, index: Int) {
        val current = actions(context).toMutableList()
        val insertionIndex = index.coerceIn(0, current.size)
        val inserted = current.getOrNull(insertionIndex)?.let { action.copy(timestamp = it.timestamp) } ?: action
        current.add(insertionIndex, inserted)
        val output = JSONArray().apply { current.forEach { put(it.toJson()) } }
        prefs(context).edit().putString(KEY_ACTIONS, output.toString()).apply()
    }


    fun exportJson(context: Context): String {
        val exported = JSONArray().apply {
            actions(context).forEach { put(it.toJson()) }
        }
        return JSONObject()
            .put("format", "automation-ui-workflow")
            .put("schemaVersion", 3)
            .put("exportedAt", System.currentTimeMillis())
            .put("actions", exported)
            .toString(2)
    }

    fun importJson(context: Context, source: String, merge: Boolean = true): Int {
        val trimmed = source.trim()
        require(trimmed.isNotEmpty()) { "The selected file is empty." }
        val array = if (trimmed.startsWith("[")) {
            JSONArray(trimmed)
        } else {
            val root = JSONObject(trimmed)
            require(root.optString("format").isBlank() ||
                root.optString("format") == "automation-ui-workflow" ||
                root.optString("format") == "adb-gesture-capture"
            ) { "Unsupported workflow JSON format." }
            root.optJSONArray("actions") ?: throw IllegalArgumentException("JSON file has no actions array.")
        }

        val incoming = (0 until array.length()).map { index ->
            RecordedAction.fromJson(array.getJSONObject(index))
        }
        val supportedTypes = setOf("CLICK", "SET_TEXT", "SCROLL", "OPEN_SETTINGS", "HOME", "BACK", "GESTURE", "WAIT", "WAIT_FOR_UI")
        require(incoming.all { it.type in supportedTypes }) { "The file contains an unsupported action type." }
        require(incoming.all { it.type != "GESTURE" || isValidGesture(it) }) {
            "The file contains a gesture with missing or invalid coordinates."
        }
        require(incoming.all {
            when (it.type) {
                "WAIT" -> it.waitDurationMs in 1L..30_000L
                "WAIT_FOR_UI" -> !it.text.isNullOrBlank() && it.waitTimeoutMs in 1_000L..120_000L
                else -> true
            }
        }) { "The file contains an invalid wait action." }

        val existing = actions(context)
        val merged = if (merge) mergeRecordedActions(existing, incoming) else incoming.sortedBy { it.timestamp }
        val result = insertRecordedWaits(merged)
        val output = JSONArray().apply { result.forEach { put(it.toJson()) } }
        prefs(context).edit().putString(KEY_ACTIONS, output.toString()).apply()
        return (result.size - existing.size).coerceAtLeast(0)
    }

    fun clear(context: Context) { prefs(context).edit().putString(KEY_ACTIONS, "[]").apply() }

    fun removeLastActionIfType(context: Context, type: String): Boolean {
        val array = runCatching {
            JSONArray(prefs(context).getString(KEY_ACTIONS, "[]") ?: "[]")
        }.getOrDefault(JSONArray())
        if (array.length() == 0) return false
        val lastIndex = array.length() - 1
        val lastType = runCatching { array.getJSONObject(lastIndex).optString("type") }.getOrNull()
        if (lastType != type) return false
        array.remove(lastIndex)
        prefs(context).edit().putString(KEY_ACTIONS, array.toString()).apply()
        return true
    }

    fun replayLogs(context: Context): List<String> {
        val array = runCatching {
            JSONArray(prefs(context).getString(KEY_REPLAY_LOG, "[]") ?: "[]")
        }.getOrDefault(JSONArray())
        return (0 until array.length()).mapNotNull { index ->
            array.optString(index).takeIf { it.isNotBlank() }
        }
    }

    fun addReplayLog(context: Context, message: String) {
        val array = runCatching {
            JSONArray(prefs(context).getString(KEY_REPLAY_LOG, "[]") ?: "[]")
        }.getOrDefault(JSONArray())
        array.put(message)
        while (array.length() > 50) array.remove(0)
        prefs(context).edit().putString(KEY_REPLAY_LOG, array.toString()).apply()
    }

    fun clearReplayLog(context: Context) {
        prefs(context).edit().putString(KEY_REPLAY_LOG, "[]").apply()
    }
}

internal fun insertRecordedWaits(
    actions: List<RecordedAction>,
    thresholdMs: Long = 1_200L,
    maxWaitMs: Long = 30_000L
): List<RecordedAction> {
    val ordered = actions.withIndex()
        .sortedWith(compareBy<IndexedValue<RecordedAction>> { it.value.timestamp }.thenBy { it.index })
        .map { it.value }
    val result = mutableListOf<RecordedAction>()
    for (action in ordered) {
        val previous = result.lastOrNull()
        val isWaitAction = action.type == "WAIT" || action.type == "WAIT_FOR_UI"
        val previousIsWait = previous?.type == "WAIT" || previous?.type == "WAIT_FOR_UI"
        if (!isWaitAction && previous != null && !previousIsWait) {
            val gap = action.timestamp - previous.timestamp
            if (gap >= thresholdMs) {
                result.add(
                    RecordedAction(
                        type = "WAIT",
                        packageName = previous.packageName,
                        text = "Recorded pause",
                        viewId = null,
                        contentDescription = null,
                        className = null,
                        left = 0, top = 0, right = 0, bottom = 0,
                        screenWidth = action.screenWidth,
                        screenHeight = action.screenHeight,
                        scrollDeltaY = 0,
                        timestamp = previous.timestamp,
                        displayRotation = action.displayRotation,
                        waitDurationMs = gap.coerceAtMost(maxWaitMs)
                    )
                )
            }
        }
        result.add(action)
    }
    return result
}

internal fun isValidGesture(action: RecordedAction): Boolean {
    val kind = action.gestureKind?.uppercase() ?: return false
    if (kind !in setOf("TAP", "SWIPE", "LONG_PRESS")) return false
    val coords = listOf(action.gestureStartX, action.gestureStartY, action.gestureEndX, action.gestureEndY)
    if (coords.any { it !in 0..10_000 }) return false
    if (action.screenWidth <= 0 || action.screenHeight <= 0) return false
    return action.gestureDurationMs in 50L..5_000L
}

internal fun mergeRecordedActions(
    existing: List<RecordedAction>,
    incoming: List<RecordedAction>
): List<RecordedAction> {
    val accepted = mutableListOf<RecordedAction>()
    val consumedExisting = mutableSetOf<Int>()

    fun sameImportedAction(a: RecordedAction, b: RecordedAction): Boolean =
        a.type == b.type && a.timestamp == b.timestamp && a.packageName == b.packageName &&
            a.text == b.text && a.viewId == b.viewId && a.inputValue == b.inputValue &&
            a.gestureKind == b.gestureKind && a.gestureStartX == b.gestureStartX &&
            a.gestureStartY == b.gestureStartY && a.gestureEndX == b.gestureEndX &&
            a.gestureEndY == b.gestureEndY &&
            a.waitDurationMs == b.waitDurationMs && a.waitTimeoutMs == b.waitTimeoutMs

    fun gestureCenter(action: RecordedAction): Pair<Float, Float> =
        ((action.gestureStartX + action.gestureEndX) / 20_000f) to
            ((action.gestureStartY + action.gestureEndY) / 20_000f)

    fun actionCenter(action: RecordedAction): Pair<Float, Float>? {
        if (action.right <= action.left || action.bottom <= action.top ||
            action.screenWidth <= 0 || action.screenHeight <= 0
        ) return null
        return (((action.left + action.right) / 2f) / action.screenWidth) to
            (((action.top + action.bottom) / 2f) / action.screenHeight)
    }

    fun near(a: Pair<Float, Float>, b: Pair<Float, Float>, maxDistance: Float): Boolean {
        val dx = a.first - b.first
        val dy = a.second - b.second
        return kotlin.math.sqrt(dx * dx + dy * dy) <= maxDistance
    }

    for (candidate in incoming.sortedBy { it.timestamp }) {
        if (existing.any { sameImportedAction(it, candidate) } ||
            accepted.any { sameImportedAction(it, candidate) }
        ) continue

        if (candidate.type == "GESTURE") {
            val kind = candidate.gestureKind?.uppercase()
            val center = gestureCenter(candidate)
            val matchingIndex = existing.indices
                .filter { it !in consumedExisting }
                .filter { index ->
                    val other = existing[index]
                    val elapsed = kotlin.math.abs(candidate.timestamp - other.timestamp)
                    when (kind) {
                        "TAP", "LONG_PRESS" -> {
                            val otherCenter = actionCenter(other)
                            val clickMatch = other.type == "CLICK" && elapsed <= 2_000L &&
                                otherCenter != null && near(center, otherCenter, 0.18f)
                            // A bottom navigation tap can be the semantic trigger for HOME.
                            val homeTapMatch = kind == "TAP" && other.type == "HOME" &&
                                elapsed <= 2_000L && candidate.gestureStartY >= 9_300
                            clickMatch || homeTapMatch
                        }
                        "SWIPE" -> {
                            val otherCenter = actionCenter(other)
                            val scrollMatch = other.type == "SCROLL" && elapsed <= 2_000L &&
                                otherCenter != null && near(center, otherCenter, 0.48f)
                            val startsAtBottom = candidate.gestureStartY >= 8_500 &&
                                candidate.gestureEndY < candidate.gestureStartY &&
                                candidate.gestureEndY <= 8_500
                            val homeSwipeMatch = other.type == "HOME" && elapsed <= 2_000L && startsAtBottom
                            val horizontal = kotlin.math.abs(candidate.gestureEndX - candidate.gestureStartX) >
                                kotlin.math.abs(candidate.gestureEndY - candidate.gestureStartY)
                            val leftEdgeBack = candidate.gestureStartX <= 500 &&
                                candidate.gestureEndX > candidate.gestureStartX
                            val rightEdgeBack = candidate.gestureStartX >= 9_500 &&
                                candidate.gestureEndX < candidate.gestureStartX
                            val backSwipeMatch = other.type == "BACK" && elapsed <= 2_000L &&
                                horizontal && (leftEdgeBack || rightEdgeBack)
                            scrollMatch || homeSwipeMatch || backSwipeMatch
                        }
                        else -> false
                    }
                }
                .minByOrNull { index -> kotlin.math.abs(candidate.timestamp - existing[index].timestamp) }

            if (matchingIndex != null) {
                consumedExisting.add(matchingIndex)
                continue
            }
        }
        accepted.add(candidate)
    }
    return (existing + accepted).sortedBy { it.timestamp }
}
