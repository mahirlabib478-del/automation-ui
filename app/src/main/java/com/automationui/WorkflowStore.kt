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
    val schemaVersion: Int = 2
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
            inputValue = obj.optString("inputValue").takeUnless { it == "null" },
            hintText = obj.optString("hintText").takeUnless { it == "null" || it.isBlank() },
            displayRotation = obj.optInt("displayRotation", 0),
            schemaVersion = obj.optInt("schemaVersion", 1)
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
        array.put(action.toJson())
        prefs(context).edit().putString(KEY_ACTIONS, array.toString()).apply()
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
