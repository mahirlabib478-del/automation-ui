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
import android.provider.Settings
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
    private var replayActionIndex = 0
    private var replayActionCount = 0
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
                (lastForegroundPackage == null || !isLauncher(lastForegroundPackage!!))
            ) {
                WorkflowStore.addAction(this, emptyAction("HOME", null, System.currentTimeMillis()))
                WorkflowStore.setStatus(this, "Recorded HOME")
            }
            if (packageName != null) lastForegroundPackage = packageName
        }

        if (!WorkflowStore.isRecording(this) || replaying) return

        // The app's own Record/Stop/Replay controls are control-plane UI, not
        // part of the user's workflow. Recording them makes replay start with
        // a click on the dashboard instead of the actual task.
        if (packageName == this.packageName) return

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
        var current = source
        var ownsCurrent = false
        repeat(4) {
            val node = current ?: return@repeat
            if (!node.isPassword && !node.isEditable) {
                val label = (node.text?.toString() ?: node.contentDescription?.toString())
                    ?.trim()?.take(180)?.takeIf { it.isNotBlank() }
                if (label != null) {
                    if (ownsCurrent) node.recycle()
                    return label
                }
            }
            val parent = node.parent
            if (ownsCurrent) node.recycle()
            current = parent
            ownsCurrent = true
        }
        if (ownsCurrent) current?.recycle()
        return event.text?.joinToString(" ")?.trim()?.take(180)?.takeIf { it.isNotBlank() }
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
        WorkflowStore.clearReplayLog(this)
        replaying = true
        replayActionIndex = 0
        replayActionCount = actions.size
        WorkflowStore.setRecording(this, false)
        setReplayStatus("Replay started: ${actions.size} actions")
        runActionAt(actions, 0)
    }

    private fun stopReplay() {
        replaying = false
        handler.removeCallbacksAndMessages(null)
        setReplayStatus("Replay stopped")
    }

    private fun setReplayStatus(message: String) {
        val prefix = if (replayActionIndex > 0 && replayActionCount > 0) {
            "Action ${replayActionIndex}/${replayActionCount}: "
        } else ""
        val line = prefix + message
        WorkflowStore.setStatus(this, line)
        WorkflowStore.addReplayLog(this, line)
    }

    private fun runActionAt(actions: List<RecordedAction>, index: Int) {
        if (!replaying) return
        if (index >= actions.size) {
            replaying = false
            replayActionIndex = 0
            setReplayStatus("Replay finished")
            return
        }

        val action = actions[index]
        replayActionIndex = index + 1
        setReplayStatus("Running ${action.type}")
        val delay = if (index == 0) 0L else
            (action.timestamp - actions[index - 1].timestamp).coerceIn(250L, 3000L)

        handler.postDelayed({
            if (!replaying) return@postDelayed
            executeAction(action, 0, actions.getOrNull(index + 1)) {
                runActionAt(actions, index + 1)
            }
        }, delay)
    }

    private fun executeAction(
        action: RecordedAction,
        attempt: Int,
        nextAction: RecordedAction?,
        done: () -> Unit
    ) {
        if (!replaying) return

        when (action.type) {
            "OPEN_SETTINGS" -> {
                runCatching {
                    startActivity(
                        Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                }.onSuccess {
                    setReplayStatus("Opened Android Settings")
                    waitForNextTarget(nextAction, 600L, 0L, done)
                }.onFailure {
                    setReplayStatus("Could not open Android Settings")
                    done()
                }
            }

            "HOME" -> {
                performGlobalAction(GLOBAL_ACTION_HOME)
                setReplayStatus("HOME action sent")
                waitForNextTarget(nextAction, 350L, 0L, done)
            }

            "BACK" -> {
                performGlobalAction(GLOBAL_ACTION_BACK)
                setReplayStatus("BACK action sent")
                waitForNextTarget(nextAction, 350L, 0L, done)
            }

            "CLICK", "SET_TEXT", "SCROLL" -> {
                val root = rootInActiveWindow
                val rootPackage = root?.packageName?.toString()

                if (root == null || (action.packageName != null && rootPackage != action.packageName)) {
                    root?.recycle()
                    if (attempt < 12) {
                        handler.postDelayed(
                            { executeAction(action, attempt + 1, nextAction, done) },
                            250L
                        )
                    } else {
                        setReplayStatus("Skipped ${action.type}: expected screen ${action.packageName ?: "(unknown)"} not active")
                        done()
                    }
                    return
                }

                val node = findNode(root, action)
                root.recycle()

                when (action.type) {
                    "CLICK" -> {
                        if (node != null) {
                            val clicked = clickNodeOrParent(node)
                            if (clicked) {
                                setReplayStatus("CLICK selector matched and activated")
                                waitForNextTarget(nextAction, 350L, 0L, done)
                            } else {
                                // The matched node was not actionable. A coordinate
                                // fallback is safer here than choosing another selector.
                                if (hasValidBounds(action)) {
                                    setReplayStatus("CLICK used coordinate fallback")
                                    dispatchTap(action) {
                                        waitForNextTarget(nextAction, 350L, 0L, done)
                                    }
                                } else {
                                    setReplayStatus("Skipped click: matched item is not clickable")
                                    done()
                                }
                            }
                        } else if (!hasSemanticSelector(action) && hasValidBounds(action)) {
                            setReplayStatus("CLICK used coordinate fallback")
                            dispatchTap(action) {
                                waitForNextTarget(nextAction, 350L, 0L, done)
                            }
                        } else if (attempt < 10) {
                            // Do not tap stale coordinates while a new Settings screen
                            // is still loading. Wait for the recorded target to appear.
                            handler.postDelayed(
                                { executeAction(action, attempt + 1, nextAction, done) },
                                250L
                            )
                        } else {
                            setReplayStatus("Skipped click: recorded UI target not found")
                            done()
                        }
                    }

                    "SET_TEXT" -> {
                        if (node == null) {
                            if (attempt < 10) {
                                handler.postDelayed(
                                    { executeAction(action, attempt + 1, nextAction, done) },
                                    250L
                                )
                            } else {
                                setReplayStatus("Skipped text input: recorded field not found")
                                done()
                            }
                        } else {
                            val result = if (node.isPassword) false else {
                                val args = Bundle().apply {
                                    putCharSequence(
                                        AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                                        action.text ?: ""
                                    )
                                }
                                node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
                            }
                            node.recycle()
                            setReplayStatus(if (result) "Text input applied" else "Text input failed")
                            waitForNextTarget(nextAction, 350L, 0L, done)
                        }
                    }

                    "SCROLL" -> {
                        if (node == null && hasSemanticSelector(action) && attempt < 10) {
                            handler.postDelayed(
                                { executeAction(action, attempt + 1, nextAction, done) },
                                250L
                            )
                        } else {
                            val scrolled = if (node != null) {
                                val direction = if (action.scrollDeltaY < 0) {
                                    AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
                                } else {
                                    AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
                                }
                                val result = node.performAction(direction)
                                node.recycle()
                                result
                            } else false

                            if (scrolled) {
                                setReplayStatus("Accessibility scroll applied")
                                waitForNextTarget(nextAction, 400L, 0L, done)
                            } else if (hasValidBounds(action)) {
                                setReplayStatus("Scroll used swipe fallback")
                                dispatchSwipe(action, action.scrollDeltaY >= 0) {
                                    waitForNextTarget(nextAction, 400L, 0L, done)
                                }
                            } else {
                                setReplayStatus("Skipped scroll: no usable scroll target or bounds")
                                done()
                            }
                        }
                    }
                }
            }

            else -> done()
        }
    }

    /**
     * Wait until the next recorded target is actually present. A fixed 350 ms
     * pause often taps the old Settings screen before the new screen is ready.
     */
    private fun waitForNextTarget(
        nextAction: RecordedAction?,
        minimumDelayMs: Long,
        elapsedMs: Long,
        done: () -> Unit
    ) {
        if (!replaying) return
        if (nextAction == null || nextAction.type == "HOME" || nextAction.type == "BACK") {
            handler.postDelayed({ if (replaying) done() }, minimumDelayMs)
            return
        }

        val pollDelay = 150L
        handler.postDelayed({
            if (!replaying) return@postDelayed

            val root = rootInActiveWindow
            val currentPackage = root?.packageName?.toString()
            var ready = nextAction.packageName == null || currentPackage == nextAction.packageName

            if (ready && hasSemanticSelector(nextAction)) {
                if (root == null) {
                    ready = false
                } else {
                    val target = findNode(root, nextAction)
                    ready = target != null
                    target?.recycle()
                }
            }

            root?.recycle()
            val nextElapsed = elapsedMs + pollDelay
            if (ready && nextElapsed >= minimumDelayMs) {
                done()
            } else if (nextElapsed >= 5000L) {
                setReplayStatus("Next screen/target timed out; replay continuing")
                done()
            } else {
                waitForNextTarget(nextAction, minimumDelayMs, nextElapsed, done)
            }
        }, pollDelay)
    }

    private fun hasSemanticSelector(action: RecordedAction): Boolean =
        !action.viewId.isNullOrBlank() ||
            !action.text.isNullOrBlank() ||
            !action.contentDescription.isNullOrBlank()

    private fun hasValidBounds(action: RecordedAction): Boolean =
        action.right > action.left &&
            action.bottom > action.top &&
            action.screenWidth > 0 &&
            action.screenHeight > 0

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
        val candidates = mutableListOf<AccessibilityNodeInfo>()
        collectNodes(root, candidates)

        var best: AccessibilityNodeInfo? = null
        var bestScore = Int.MIN_VALUE
        for (candidate in candidates) {
            val score = scoreNode(candidate, action)
            if (score > bestScore) {
                best = candidate
                bestScore = score
            }
        }

        val minimumScore = if (hasSemanticSelector(action)) 8 else 1
        if (best == null || bestScore < minimumScore) {
            candidates.forEach { it.recycle() }
            return null
        }

        candidates.filter { it !== best }.forEach { it.recycle() }
        return best
    }

    private fun collectNodes(
        node: AccessibilityNodeInfo,
        output: MutableList<AccessibilityNodeInfo>
    ) {
        output.add(AccessibilityNodeInfo.obtain(node))
        for (index in 0 until node.childCount) {
            val child = node.getChild(index) ?: continue
            collectNodes(child, output)
            child.recycle()
        }
    }

    /**
     * Common Android Settings rows reuse IDs such as "title". Rank all matching
     * nodes instead of taking the first ID match; prefer the recorded label and
     * use recorded bounds only as a disambiguator.
     */
    private fun scoreNode(node: AccessibilityNodeInfo, action: RecordedAction): Int {
        if (!node.isVisibleToUser || !node.isEnabled) return Int.MIN_VALUE

        var score = 0
        val expectedId = action.viewId?.takeIf { it.isNotBlank() }
        val actualId = node.viewIdResourceName
        if (expectedId != null) {
            score += if (actualId == expectedId) 14 else -4
        }

        val expectedText = action.text?.trim()?.takeIf { it.isNotBlank() }
        val actualText = node.text?.toString()?.trim().orEmpty()
        val actualDescription = node.contentDescription?.toString()?.trim().orEmpty()

        if (expectedText != null) {
            when {
                actualText.equals(expectedText, ignoreCase = true) -> score += 24
                actualDescription.equals(expectedText, ignoreCase = true) -> score += 18
                actualText.contains(expectedText, ignoreCase = true) ||
                    expectedText.contains(actualText, ignoreCase = true) && actualText.isNotBlank() -> score += 12
                actualText.isNotBlank() || actualDescription.isNotBlank() -> score -= 24
                else -> score -= 8
            }
        }

        val expectedDescription = action.contentDescription?.trim()?.takeIf { it.isNotBlank() }
        if (expectedDescription != null) {
            when {
                actualDescription.equals(expectedDescription, ignoreCase = true) -> score += 24
                actualText.equals(expectedDescription, ignoreCase = true) -> score += 18
                actualDescription.isNotBlank() || actualText.isNotBlank() -> score -= 24
                else -> score -= 8
            }
        }

        val expectedClass = action.className?.takeIf { it.isNotBlank() }
        if (expectedClass != null && node.className?.toString() == expectedClass) score += 2
        if (node.isClickable) score += 3
        if (action.type == "SCROLL" && node.isScrollable) score += 10

        if (hasValidBounds(action)) {
            val recordedX = ((action.left + action.right) / 2f) / action.screenWidth.toFloat()
            val recordedY = ((action.top + action.bottom) / 2f) / action.screenHeight.toFloat()
            val bounds = Rect()
            node.getBoundsInScreen(bounds)
            val currentWidth = resources.displayMetrics.widthPixels.coerceAtLeast(1)
            val currentHeight = resources.displayMetrics.heightPixels.coerceAtLeast(1)
            val currentX = bounds.exactCenterX() / currentWidth.toFloat()
            val currentY = bounds.exactCenterY() / currentHeight.toFloat()
            val dx = recordedX - currentX
            val dy = recordedY - currentY
            val distance = kotlin.math.sqrt(dx * dx + dy * dy)
            score += (12f - distance * 24f).toInt().coerceIn(-12, 12)
        }

        return score
    }

    private fun dispatchTap(action: RecordedAction, done: () -> Unit) {
        val point = scaledCenter(action) ?: run {
            setReplayStatus("Skipped click: no usable selector or coordinates")
            done()
            return
        }
        val path = Path().apply { moveTo(point.first, point.second) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 90))
            .build()
        val accepted = dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                handler.postDelayed(done, 350L)
            }
            override fun onCancelled(gestureDescription: GestureDescription?) {
                setReplayStatus("Tap gesture cancelled")
                done()
            }
        }, handler)
        if (!accepted) {
            setReplayStatus("Tap gesture was rejected by Android")
            done()
        }
    }

    private fun dispatchSwipe(action: RecordedAction, forward: Boolean, done: () -> Unit) {
        val displayWidth = resources.displayMetrics.widthPixels.coerceAtLeast(2)
        val displayHeight = resources.displayMetrics.heightPixels.coerceAtLeast(2)

        val x: Float
        val yStart: Float
        val yEnd: Float
        if (hasValidBounds(action)) {
            val left = scale(action.left, action.screenWidth, displayWidth)
            val right = scale(action.right, action.screenWidth, displayWidth)
            val top = scale(action.top, action.screenHeight, displayHeight)
            val bottom = scale(action.bottom, action.screenHeight, displayHeight)
            val safeLeft = left.coerceIn(0, displayWidth - 1)
            val safeRight = right.coerceIn(safeLeft + 1, displayWidth)
            val safeTop = top.coerceIn(0, displayHeight - 1)
            val safeBottom = bottom.coerceIn(safeTop + 1, displayHeight)
            x = (safeLeft + safeRight) / 2f
            yStart = if (forward) {
                safeBottom - (safeBottom - safeTop) * 0.15f
            } else {
                safeTop + (safeBottom - safeTop) * 0.15f
            }
            yEnd = if (forward) {
                safeTop + (safeBottom - safeTop) * 0.15f
            } else {
                safeBottom - (safeBottom - safeTop) * 0.15f
            }
        } else {
            // Some scroll events have no source bounds. Use a broad central swipe
            // instead of accidentally generating a 1-pixel gesture at (0, 0).
            x = displayWidth / 2f
            yStart = if (forward) displayHeight * 0.82f else displayHeight * 0.18f
            yEnd = if (forward) displayHeight * 0.18f else displayHeight * 0.82f
        }

        val path = Path().apply { moveTo(x, yStart); lineTo(x, yEnd) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 350))
            .build()
        val accepted = dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                handler.postDelayed(done, 400L)
            }
            override fun onCancelled(gestureDescription: GestureDescription?) {
                setReplayStatus("Swipe gesture cancelled")
                done()
            }
        }, handler)
        if (!accepted) {
            setReplayStatus("Swipe gesture was rejected by Android")
            done()
        }
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
