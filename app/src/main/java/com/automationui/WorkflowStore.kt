package com.automationui

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class RecordedAction(
    val type: String,
    val packageName: String?,
    val text: String?,
    val viewId: String?,
    val timestamp: Long
) {
    fun toJson() = JSONObject().apply {
        put("type", type)
        put("packageName", packageName ?: JSONObject.NULL)
        put("text", text ?: JSONObject.NULL)
        put("viewId", viewId ?: JSONObject.NULL)
        put("timestamp", timestamp)
    }
    companion object {
        fun fromJson(obj: JSONObject) = RecordedAction(
            type = obj.optString("type"),
            packageName = obj.optString("packageName").takeUnless { it == "null" || it.isBlank() },
            text = obj.optString("text").takeUnless { it == "null" || it.isBlank() },
            viewId = obj.optString("viewId").takeUnless { it == "null" || it.isBlank() },
            timestamp = obj.optLong("timestamp")
        )
    }
}

object WorkflowStore {
    private const val PREFS = "automation_ui"
    private const val KEY_ACTIONS = "actions"
    private const val KEY_RECORDING = "recording"
    private const val KEY_STATUS = "status"

    fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    fun isRecording(context: Context) = prefs(context).getBoolean(KEY_RECORDING, false)
    fun setRecording(context: Context, value: Boolean) {
        prefs(context).edit().putBoolean(KEY_RECORDING, value).apply()
    }
    fun setStatus(context: Context, value: String) {
        prefs(context).edit().putString(KEY_STATUS, value).apply()
    }
    fun status(context: Context) = prefs(context).getString(KEY_STATUS, "Ready") ?: "Ready"

    fun actions(context: Context): MutableList<RecordedAction> {
        val array = runCatching {
            JSONArray(prefs(context).getString(KEY_ACTIONS, "[]") ?: "[]")
        }.getOrDefault(JSONArray())
        return MutableList(array.length()) { index -> RecordedAction.fromJson(array.getJSONObject(index)) }
    }
    fun addAction(context: Context, action: RecordedAction) {
        val array = JSONArray(prefs(context).getString(KEY_ACTIONS, "[]") ?: "[]")
        array.put(action.toJson())
        prefs(context).edit().putString(KEY_ACTIONS, array.toString()).apply()
    }
    fun clear(context: Context) {
        prefs(context).edit().putString(KEY_ACTIONS, "[]").apply()
    }
}
