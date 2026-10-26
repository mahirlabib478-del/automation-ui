package com.automationui

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Records UI actions exposed by Android Accessibility events and replays the
 * supported actions. Android does not expose every raw touch from other apps;
 * coordinate replay is a fallback for accessibility-observable clicks/scrolls.
 */
class AutomationAccessibilityService : AccessibilityService() {
    private val handler = Handler(Looper.getMainLooper())
    private var replaying = false
    private var lastForegroundPackage: String? = null

    private val replayReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                ACTION_REPLAY -> replayActions()
                ACTION_STOP -> stopReplay()
            }
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        val filter = IntentFilter().apply {
            addAction(ACTION_REPLAY)
            addAction(ACTION_STOP)
        }
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(replayReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("DEPRECATION")
            registerReceiver(replayReceiver, filter)
        }
        WorkflowStore.setStatus(this, "Accessibility service connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event ?: return
        val packageName = event.packageName?.toString()

        if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            if (WorkflowStore.isRecording(this) && !replaying &&
                packageName != null && isLauncher(packageName) &&
                lastForegroundPackage != null && !isLauncher(lastForegroundPackage!!)
            ) {
                WorkflowStore.addAction(this, emptyAction("HOME", null, System.currentTimeMillis()))
                WorkflowStore.setStatus(this, "Recorded HOME")
            }
            if (packageName != null) lastForegroundPackage = packageName
        }

        if (!WorkflowStore.isRecording(this) || replaying) return

        when (event.eventType) {
            AccessibilityEvent.TYPE_VIEW_CLICKED -> {
                val source = event.source
                val systemAction = detectSystemNavigationAction(packageName, source)
                val actionType = systemAction ?: "CLICK"
                val action = buildAction(
                    type = actionType,
                    event = event,
                    source = source,
                    textOverride = if (actionType == "CLICK") safeLabel(source, event) else null,
                    scrollDeltaY = 0
                )
                source?.recycle()
                WorkflowStore.addAction(this, action)
                WorkflowStore.setStatus(this, "Recorded $actionType")
            }

            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> {
                if (!WorkflowStore.isRecordingText(this)) return
                val source = event.source ?: return
                val isSafeEditableField = source.isEditable && !source.isPassword
                val value = if (isSafeEditableField) source.text?.toString() else null
                if (isSafeEditableField && value != null) {
                    val action = buildAction("SET_TEXT", event, source, value, 0)
                    source.recycle()
                    WorkflowStore.addAction(this, action)
                    WorkflowStore.setStatus(this, "Recorded text input (opt-in)")
                } else {
                    source.recycle()
                }
            }

            AccessibilityEvent.TYPE_VIEW_SCROLLED -> {
                val source = event.source
                val delta = if (Build.VERSION.SDK_INT >= 28) event.scrollDeltaY else 0
                val action = buildAction("SCROLL", event, source, null, delta)
                source?.recycle()
                WorkflowStore.addAction(this, action)
                WorkflowStore.setStatus(this, "Recorded SCROLL")
            }
        }
    }

    private fun safeLabel(source: AccessibilityNodeInfo?, event: AccessibilityEvent): String? {
        if (source == null || source.isPassword || source.isEditable) return null
        return (source.text?.toString() ?: source.contentDescription?.toString()
            ?: event.text?.joinToString(" "))?.trim()?.take(180)?.takeIf { it.isNotBlank() }
    }

    private fun detectSystemNavigationAction(
        packageName: String?,
        source: AccessibilityNodeInfo?
    ): String? {
        if (packageName != "com.android.systemui" && packageName != "com.android.systemui.navigationbar") return null
        val label = (source?.contentDescription?.toString() ?: source?.text?.toString())
            ?.trim()?.lowercase() ?: return null
        return when {
            label == "back" || label == "back button" -> "BACK"
            label == "home" || label == "home button" -> "HOME"
            else -> null
        }
    }

    private fun buildAction(
        type: String,
        event: AccessibilityEvent,
        source: AccessibilityNodeInfo?,
        textOverride: String?,
        scrollDeltaY: Int
    ): RecordedAction {
        val bounds = Rect()
        source?.getBoundsInScreen(bounds)
        val sourceText = source?.takeIf { !it.isPassword && !it.isEditable }?.text?.toString()
        val label = textOverride ?: sourceText
        return RecordedAction(
            type = type,
            packageName = event.packageName?.toString(),
            text = label,
            viewId = source?.viewIdResourceName,
            contentDescription = source?.contentDescription?.toString(),
            className = source?.className?.toString(),
            left = bounds.left,
            top = bounds.top,
            right = bounds.right,
            bottom = bounds.bottom,
            screenWidth = resources.displayMetrics.widthPixels,
            screenHeight = resources.displayMetrics.heightPixels,
            scrollDeltaY = scrollDeltaY,
            timestamp = System.currentTimeMillis()
        )
    }

    private fun emptyAction(type: String, packageName: String?, timestamp: Long) = RecordedAction(
        type = type,
        packageName = packageName,
        text = null,
        viewId = null,
        contentDescription = null,
        className = null,
        left = 0, top = 0, right = 0, bottom = 0,
        screenWidth = resources.displayMetrics.widthPixels,
        screenHeight = resources.displayMetrics.heightPixels,
        scrollDeltaY = 0,
        timestamp = timestamp
    )

    private fun isLauncher(packageName: String): Boolean {
        val name = packageName.lowercase()
        return name.contains("launcher") ||
            name == "com.sec.android.app.launcher" ||
            name == "com.miui.home" ||
            name == "com.oppo.launcher" ||
            name == "com.vivo.launcher"
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
        WorkflowStore.setStatus(this, "Replaying ${actions.size} actions…")
        runActionAt(actions, 0)
    }

    private fun stopReplay() {
        replaying = false
        handler.removeCallbacksAndMessages(null)
        WorkflowStore.setStatus(this, "Replay stopped")
    }

    private fun runActionAt(actions: List<RecordedAction>, index: Int) {
        if (!replaying) return
        if (index >= actions.size) {
            replaying = false
            WorkflowStore.setStatus(this, "Replay finished")
            return
        }
        val action = actions[index]
        val delay = if (index == 0) 0L else
            (action.timestamp - actions[index - 1].timestamp).coerceIn(250L, 3000L)

        handler.postDelayed({
            if (!replaying) return@postDelayed
            executeAction(action, 0) {
                runActionAt(actions, index + 1)
            }
        }, delay)
    }

    private fun executeAction(action: RecordedAction, attempt: Int, done: () -> Unit) {
        if (!replaying) return
        when (action.type) {
            "HOME" -> {
                performGlobalAction(GLOBAL_ACTION_HOME)
                handler.postDelayed(done, 500L)
            }
            "BACK" -> {
                performGlobalAction(GLOBAL_ACTION_BACK)
                handler.postDelayed(done, 350L)
            }
            "CLICK", "SET_TEXT", "SCROLL" -> {
                val root = rootInActiveWindow
                val rootPackage = root?.packageName?.toString()
                if (root == null || (action.packageName != null && rootPackage != action.packageName)) {
                    root?.recycle()
                    if (attempt < 12) {
                        handler.postDelayed({ executeAction(action, attempt + 1, done) }, 300L)
                    } else {
                        WorkflowStore.setStatus(this, "Skipped ${action.type}: expected app screen did not appear")
                        done()
                    }
                    return
                }

                val node = findNode(root, action)
                root.recycle()
                when (action.type) {
                    "CLICK" -> {
                        val clicked = node?.let { clickNodeOrParent(it) } ?: false
                        if (clicked) handler.postDelayed(done, 350L)
                        else dispatchTap(action, done)
                    }
                    "SET_TEXT" -> {
                        if (node == null) {
                            WorkflowStore.setStatus(this, "Skipped text input: field not found")
                            done()
                        } else {
                            val result = if (node.isPassword) false else {
                                val args = Bundle().apply {
                                    putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, action.text ?: "")
                                }
                                node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
                            }
                            node.recycle()
                            if (!result) WorkflowStore.setStatus(this, "Text input could not be replayed")
                            handler.postDelayed(done, 350L)
                        }
                    }
                    "SCROLL" -> {
                        val direction = if (action.scrollDeltaY < 0) {
                            AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
                        } else {
                            AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
                        }
                        val scrolled = node?.performAction(direction) ?: false
                        node?.recycle()
                        if (scrolled) handler.postDelayed(done, 400L)
                        else dispatchSwipe(action, action.scrollDeltaY >= 0, done)
                    }
                }
            }
            else -> done()
        }
    }

    private fun clickNodeOrParent(node: AccessibilityNodeInfo): Boolean {
        var current: AccessibilityNodeInfo? = node
        repeat(5) {
            val candidate = current ?: return false
            if (candidate.isClickable && candidate.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                candidate.recycle()
                return true
            }
            val parent = candidate.parent
            candidate.recycle()
            current = parent
        }
        current?.recycle()
        return false
    }

    private fun findNode(root: AccessibilityNodeInfo, action: RecordedAction): AccessibilityNodeInfo? {
        val id = action.viewId
        if (!id.isNullOrBlank()) {
            val matches = runCatching { root.findAccessibilityNodeInfosByViewId(id) }.getOrNull()
            matches?.firstOrNull { it.isVisibleToUser }?.let { selected ->
                matches.filter { it !== selected }.forEach { it.recycle() }
                return selected
            }
            matches?.forEach { it.recycle() }
        }

        val description = action.contentDescription
        if (!description.isNullOrBlank()) {
            val matches = runCatching { root.findAccessibilityNodeInfosByText(description) }.getOrNull()
            matches?.firstOrNull()?.let { selected ->
                matches.filter { it !== selected }.forEach { it.recycle() }
                return selected
            }
            matches?.forEach { it.recycle() }
        }

        val text = action.text
        if (!text.isNullOrBlank()) {
            val matches = runCatching { root.findAccessibilityNodeInfosByText(text) }.getOrNull()
            matches?.firstOrNull()?.let { selected ->
                matches.filter { it !== selected }.forEach { it.recycle() }
                return selected
            }
            matches?.forEach { it.recycle() }
        }

        for (i in 0 until root.childCount) {
            val child = root.getChild(i) ?: continue
            val found = findNode(child, action)
            child.recycle()
            if (found != null) return found
        }
        return null
    }

    private fun dispatchTap(action: RecordedAction, done: () -> Unit) {
        val point = scaledCenter(action) ?: run {
            WorkflowStore.setStatus(this, "Skipped click: no usable selector or coordinates")
            done()
            return
        }
        val path = Path().apply { moveTo(point.first, point.second) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 90))
            .build()
        dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                handler.postDelayed(done, 350L)
            }
            override fun onCancelled(gestureDescription: GestureDescription?) {
                WorkflowStore.setStatus(this@AutomationAccessibilityService, "Tap gesture cancelled")
                done()
            }
        }, handler)
    }

    private fun dispatchSwipe(action: RecordedAction, forward: Boolean, done: () -> Unit) {
        val displayWidth = resources.displayMetrics.widthPixels
        val displayHeight = resources.displayMetrics.heightPixels
        val left = scale(action.left, action.screenWidth, displayWidth)
        val right = scale(action.right, action.screenWidth, displayWidth)
        val top = scale(action.top, action.screenHeight, displayHeight)
        val bottom = scale(action.bottom, action.screenHeight, displayHeight)
        val safeLeft = left.coerceIn(0, displayWidth - 1)
        val safeRight = right.coerceIn(safeLeft + 1, displayWidth)
        val safeTop = top.coerceIn(0, displayHeight - 1)
        val safeBottom = bottom.coerceIn(safeTop + 1, displayHeight)
        val x = (safeLeft + safeRight) / 2f
        val yStart = if (forward) safeBottom - (safeBottom - safeTop) * 0.15f else safeTop + (safeBottom - safeTop) * 0.15f
        val yEnd = if (forward) safeTop + (safeBottom - safeTop) * 0.15f else safeBottom - (safeBottom - safeTop) * 0.15f
        val path = Path().apply { moveTo(x, yStart); lineTo(x, yEnd) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 350))
            .build()
        dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                handler.postDelayed(done, 400L)
            }
            override fun onCancelled(gestureDescription: GestureDescription?) {
                WorkflowStore.setStatus(this@AutomationAccessibilityService, "Swipe gesture cancelled")
                done()
            }
        }, handler)
    }

    private fun scaledCenter(action: RecordedAction): Pair<Float, Float>? {
        if (action.right <= action.left || action.bottom <= action.top) return null
        val width = resources.displayMetrics.widthPixels
        val height = resources.displayMetrics.heightPixels
        val x = scale((action.left + action.right) / 2, action.screenWidth, width).coerceIn(1, width - 2)
        val y = scale((action.top + action.bottom) / 2, action.screenHeight, height).coerceIn(1, height - 2)
        return x.toFloat() to y.toFloat()
    }

    private fun scale(value: Int, recordedSize: Int, currentSize: Int): Int {
        if (recordedSize <= 0) return value
        return ((value.toFloat() / recordedSize.toFloat()) * currentSize).toInt()
    }

    override fun onInterrupt() {
        stopReplay()
        WorkflowStore.setStatus(this, "Accessibility service interrupted")
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(replayReceiver) }
        replaying = false
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    companion object {
        const val ACTION_REPLAY = "com.automationui.ACTION_REPLAY"
        const val ACTION_STOP = "com.automationui.ACTION_STOP"
    }
}
