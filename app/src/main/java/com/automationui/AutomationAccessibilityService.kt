package com.automationui

import android.accessibilityservice.AccessibilityService
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

class AutomationAccessibilityService : AccessibilityService() {
    private val handler = Handler(Looper.getMainLooper())
    private var replaying = false

    private val replayReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == ACTION_REPLAY) replayActions()
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        val filter = IntentFilter(ACTION_REPLAY)
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(replayReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        else {
            @Suppress("DEPRECATION")
            registerReceiver(replayReceiver, filter)
        }
        WorkflowStore.setStatus(this, "Accessibility service connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event ?: return
        if (!WorkflowStore.isRecording(this) || replaying) return
        val type = when (event.eventType) {
            AccessibilityEvent.TYPE_VIEW_CLICKED -> "CLICK"
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> "TEXT_CHANGED"
            AccessibilityEvent.TYPE_VIEW_SCROLLED -> "SCROLLED"
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> "WINDOW_CHANGED"
            else -> return
        }
        val text = event.text?.joinToString(" ")?.trim()?.take(180)?.takeIf { it.isNotBlank() }
        val source = event.source
        val viewId = source?.viewIdResourceName
        source?.recycle()
        WorkflowStore.addAction(this, RecordedAction(
            type = type,
            packageName = event.packageName?.toString(),
            // Do not persist typed text to reduce accidental secret capture.
            text = if (type == "TEXT_CHANGED") null else text,
            viewId = viewId,
            timestamp = System.currentTimeMillis()
        ))
        WorkflowStore.setStatus(this, "Recorded $type")
    }

    private fun replayActions() {
        if (replaying) return
        val actions = WorkflowStore.actions(this)
        if (actions.isEmpty()) {
            WorkflowStore.setStatus(this, "No actions recorded")
            return
        }
        replaying = true
        WorkflowStore.setRecording(this, false)
        WorkflowStore.setStatus(this, "Replaying ${actions.size} events…")
        runActionAt(actions, 0)
    }

    private fun runActionAt(actions: List<RecordedAction>, index: Int) {
        if (index >= actions.size) {
            replaying = false
            WorkflowStore.setStatus(this, "Replay finished")
            return
        }
        val action = actions[index]
        val delay = if (index == 0) 0L else (action.timestamp - actions[index - 1].timestamp).coerceIn(250L, 3000L)
        handler.postDelayed({
            if (!replaying) return@postDelayed
            when (action.type) {
                "CLICK" -> clickMatchingNode(action)
                "SCROLLED" -> WorkflowStore.setStatus(this, "Scroll replay is not yet implemented")
                "WINDOW_CHANGED", "TEXT_CHANGED" -> Unit
            }
            runActionAt(actions, index + 1)
        }, delay)
    }

    private fun clickMatchingNode(action: RecordedAction) {
        val root = rootInActiveWindow ?: return
        val node = findNode(root, action)
        if (node != null) {
            node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            node.recycle()
        } else {
            WorkflowStore.setStatus(this, "Skipped click: matching UI element not found")
        }
        root.recycle()
    }

    private fun findNode(root: AccessibilityNodeInfo, action: RecordedAction): AccessibilityNodeInfo? {
        val id = action.viewId
        if (!id.isNullOrBlank()) {
            runCatching { root.findAccessibilityNodeInfosByViewId(id) }
                .getOrNull()?.firstOrNull()?.let { return it }
        }
        val text = action.text
        if (!text.isNullOrBlank()) root.findAccessibilityNodeInfosByText(text).firstOrNull()?.let { return it }
        for (i in 0 until root.childCount) {
            val child = root.getChild(i) ?: continue
            val found = findNode(child, action)
            if (found != null) {
                if (found !== child) child.recycle()
                return found
            }
            child.recycle()
        }
        return null
    }

    override fun onInterrupt() {
        replaying = false
        WorkflowStore.setStatus(this, "Interrupted")
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(replayReceiver) }
        replaying = false
        super.onDestroy()
    }

    companion object { const val ACTION_REPLAY = "com.automationui.ACTION_REPLAY" }
}
