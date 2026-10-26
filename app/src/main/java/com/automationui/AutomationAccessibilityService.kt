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
import android.util.DisplayMetrics
import android.view.WindowManager
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
    private data class ScrollSnapshot(
        val scrollY: Int,
        val fromIndex: Int,
        val toIndex: Int,
        val timestamp: Long
    )
    private val lastScrollPositions = mutableMapOf<String, ScrollSnapshot>()

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

        // Reopening our app from the launcher is the natural way to stop a
        // same-phone recording. Stop before recording that launcher icon click,
        // so the workflow does not try to reopen the recorder during replay.
        if (WorkflowStore.isRecording(this) && !replaying &&
            packageName != null && isLauncher(packageName) &&
            event.eventType == AccessibilityEvent.TYPE_VIEW_CLICKED
        ) {
            val source = event.source
            val clickedLabel = safeLabel(source, event)
            source?.recycle()
            val ownLabel = packageManager.getApplicationLabel(applicationInfo).toString()
            if (clickedLabel.equals(ownLabel, ignoreCase = true)) {
                WorkflowStore.setRecording(this, false)
                // Opening the recorder from the launcher is a recording stop gesture,
                // not a HOME action that should replay at the end of the workflow.
                WorkflowStore.removeLastActionIfType(this, "HOME")
                WorkflowStore.setStatus(
                    this,
                    "Recording stopped when Automation UI was reopened; ${WorkflowStore.actions(this).size} actions saved"
                )
                return
            }
        }

        // The app's own Record/Stop/Replay controls are control-plane UI, not
        // part of the user's workflow. Recording them makes replay start with
        // a click on the dashboard instead of the actual task.
        if (packageName == this.packageName) return

        when (event.eventType) {
            AccessibilityEvent.TYPE_VIEW_CLICKED -> {
                val source = event.source
                val systemAction = detectSystemNavigationAction(packageName, source)
                val actionType = systemAction ?: "CLICK"
                val action = if (actionType == "CLICK") {
                    buildClickAction(event, source)
                } else {
                    buildAction(
                        type = actionType,
                        event = event,
                        source = source,
                        textOverride = null,
                        scrollDeltaY = 0
                    )
                }
                source?.recycle()
                WorkflowStore.addAction(this, action)
                val recordedLabel = action.text?.takeIf { it.isNotBlank() }?.let { ": $it" }.orEmpty()
                WorkflowStore.setStatus(this, "Recorded $actionType$recordedLabel")
            }

            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> {
                if (!WorkflowStore.isRecordingText(this)) return
                val source = event.source ?: return
                val isSafeEditableField = source.isEditable && !source.isPassword
                val value = if (isSafeEditableField) source.text?.toString() else null
                if (isSafeEditableField && value != null) {
                    val action = buildAction("SET_TEXT", event, source, null, 0, inputValue = value)
                    source.recycle()
                    WorkflowStore.addAction(this, action)
                    WorkflowStore.setStatus(this, "Recorded text input (opt-in)")
                } else {
                    source.recycle()
                }
            }

            AccessibilityEvent.TYPE_VIEW_SCROLLED -> {
                val source = event.source
                val delta = resolveScrollDelta(event, source, packageName)

                // Modern Android reports scrollDeltaY for a real scroll change.
                // A zero delta often occurs while a screen is opening/re-layouting;
                // replaying that as a forward swipe was causing phantom scrolls.
                if (delta == 0) {
                    source?.recycle()
                    return
                }

                val action = buildAction("SCROLL", event, source, null, delta)
                source?.recycle()
                WorkflowStore.addAction(this, action)
                WorkflowStore.setStatus(this, "Recorded SCROLL (ΔY $delta)")
            }
        }
    }

    private fun resolveScrollDelta(
        event: AccessibilityEvent,
        source: AccessibilityNodeInfo?,
        packageName: String?
    ): Int {
        val now = System.currentTimeMillis()
        val sourceBounds = Rect()
        source?.getBoundsInScreen(sourceBounds)
        val key = "${packageName.orEmpty()}|${source?.viewIdResourceName.orEmpty()}|${source?.className?.toString().orEmpty()}|${sourceBounds.left},${sourceBounds.top},${sourceBounds.right},${sourceBounds.bottom}"
        val previous = lastScrollPositions[key]
        val current = ScrollSnapshot(event.scrollY, event.fromIndex, event.toIndex, now)
        lastScrollPositions[key] = current

        if (lastScrollPositions.size > 30) {
            lastScrollPositions.entries.removeAll { now - it.value.timestamp > 10_000L }
            while (lastScrollPositions.size > 30) lastScrollPositions.remove(lastScrollPositions.keys.first())
        }

        if (Build.VERSION.SDK_INT >= 28 && event.scrollDeltaY != 0) return event.scrollDeltaY

        // Some apps/OEMs report TYPE_VIEW_SCROLLED with a zero pixel delta.
        // Infer direction only from a recent event on the same container.
        if (previous != null && now - previous.timestamp in 1..1_500L) {
            if (event.fromIndex >= 0 && event.toIndex >= 0 &&
                previous.fromIndex >= 0 && previous.toIndex >= 0
            ) {
                val indexDelta = (event.fromIndex + event.toIndex) -
                    (previous.fromIndex + previous.toIndex)
                if (indexDelta != 0) return indexDelta
            }
            val yDelta = event.scrollY - previous.scrollY
            if (yDelta != 0 && kotlin.math.abs(yDelta) <= realDisplaySize().second * 2) return yDelta
        }
        return 0
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

    /**
     * Click events frequently expose a non-clickable TextView as event.source,
     * even though the real touch target is its clickable parent row. Record the
     * parent's hit bounds/ID while preserving the best human-readable label.
     * This makes replay and coordinate fallback target the actual control.
     */
    private fun buildClickAction(
        event: AccessibilityEvent,
        source: AccessibilityNodeInfo?
    ): RecordedAction {
        val label = safeLabel(source, event)
        var current: AccessibilityNodeInfo? = source?.let { AccessibilityNodeInfo.obtain(it) }
        var target: AccessibilityNodeInfo? = null
        var depth = 0
        while (current != null && depth < 7 && target == null) {
            val node = current
            if (node.isClickable || node.isCheckable) {
                target = AccessibilityNodeInfo.obtain(node)
                node.recycle()
                current = null
            } else {
                val parent = node.parent
                node.recycle()
                current = parent
            }
            depth++
        }

        val chosen = target ?: current
        val bounds = Rect()
        chosen?.getBoundsInScreen(bounds)
        val targetText = chosen?.takeIf { !it.isPassword && !it.isEditable }?.text?.toString()
            ?.trim()?.takeIf { it.isNotBlank() }
        val targetDescription = chosen?.contentDescription?.toString()?.trim()
            ?.takeIf { it.isNotBlank() }
        val bestLabel = label ?: targetText ?: targetDescription
        val display = realDisplaySize()
        val action = RecordedAction(
            type = "CLICK",
            packageName = event.packageName?.toString(),
            text = bestLabel,
            viewId = chosen?.viewIdResourceName,
            contentDescription = targetDescription,
            className = chosen?.className?.toString(),
            left = bounds.left,
            top = bounds.top,
            right = bounds.right,
            bottom = bounds.bottom,
            screenWidth = display.first,
            screenHeight = display.second,
            scrollDeltaY = 0,
            timestamp = System.currentTimeMillis(),
            hintText = chosen?.hintText?.toString()?.takeIf { it.isNotBlank() },
            displayRotation = currentDisplayRotation()
        )
        target?.recycle()
        current?.recycle()
        return action
    }

    private fun buildAction(
        type: String,
        event: AccessibilityEvent,
        source: AccessibilityNodeInfo?,
        textOverride: String?,
        scrollDeltaY: Int,
        inputValue: String? = null
    ): RecordedAction {
        val bounds = Rect()
        source?.getBoundsInScreen(bounds)
        val sourceText = source?.takeIf { !it.isPassword && !it.isEditable }?.text?.toString()
        val hint = source?.hintText?.toString()?.takeIf { it.isNotBlank() }
        val description = source?.contentDescription?.toString()?.takeIf { it.isNotBlank() }
        val label = when (type) {
            "SCROLL" -> textOverride
            "SET_TEXT" -> textOverride ?: hint ?: description
            else -> textOverride ?: sourceText
        }
        val display = realDisplaySize()
        return RecordedAction(
            type = type,
            packageName = event.packageName?.toString(),
            text = label,
            viewId = source?.viewIdResourceName,
            contentDescription = description,
            className = source?.className?.toString(),
            left = bounds.left,
            top = bounds.top,
            right = bounds.right,
            bottom = bounds.bottom,
            screenWidth = display.first,
            screenHeight = display.second,
            scrollDeltaY = scrollDeltaY,
            timestamp = System.currentTimeMillis(),
            inputValue = inputValue,
            hintText = hint,
            displayRotation = currentDisplayRotation()
        )
    }

    private fun emptyAction(type: String, packageName: String?, timestamp: Long): RecordedAction {
        val display = realDisplaySize()
        return RecordedAction(
            type = type,
            packageName = packageName,
            text = null,
            viewId = null,
            contentDescription = null,
            className = null,
            left = 0, top = 0, right = 0, bottom = 0,
            screenWidth = display.first,
            screenHeight = display.second,
            scrollDeltaY = 0,
            timestamp = timestamp,
            displayRotation = currentDisplayRotation()
        )
    }

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
        val delay = ReplayPolicy.delayMs(actions.getOrNull(index - 1)?.timestamp, action.timestamp)

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
            "GESTURE" -> {
                if (!isValidGesture(action)) {
                    setReplayStatus("Skipped gesture: invalid or missing coordinates")
                    done()
                } else if (!ReplayPolicy.gestureRotationMatches(action.displayRotation, currentDisplayRotation())) {
                    setReplayStatus("Skipped gesture: display orientation changed")
                    done()
                } else {
                    dispatchRecordedGesture(action) {
                        waitForNextTarget(nextAction, 150L, 0L, done)
                    }
                }
            }

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
                                if (coordinateFallbackAllowed(action)) {
                                    setReplayStatus("CLICK used coordinate fallback")
                                    dispatchTap(action) {
                                        waitForNextTarget(nextAction, 350L, 0L, done)
                                    }
                                } else {
                                    setReplayStatus("Skipped click: matched item is not clickable")
                                    done()
                                }
                            }
                        } else if (!hasSemanticSelector(action) && coordinateFallbackAllowed(action)) {
                            setReplayStatus("CLICK used coordinate fallback")
                            dispatchTap(action) {
                                waitForNextTarget(nextAction, 350L, 0L, done)
                            }
                        } else if (attempt < 10) {
                            handler.postDelayed(
                                { executeAction(action, attempt + 1, nextAction, done) },
                                250L
                            )
                        } else if (coordinateFallbackAllowed(action)) {
                            val currentRoot = rootInActiveWindow
                            val currentPackage = currentRoot?.packageName?.toString()
                            val nearby = if (currentRoot != null && currentPackage == action.packageName) {
                                findNodeNearRecordedBounds(currentRoot, action)
                            } else null
                            currentRoot?.recycle()
                            if (nearby != null) {
                                setReplayStatus("Selector unavailable; matched visible element near recorded target")
                                val clicked = clickNodeOrParent(nearby)
                                if (clicked) {
                                    waitForNextTarget(nextAction, 350L, 0L, done)
                                } else {
                                    setReplayStatus("Skipped click: nearby element was not actionable")
                                    done()
                                }
                            } else {
                                setReplayStatus("Skipped click: target not found; unsafe coordinate fallback blocked")
                                done()
                            }
                        } else {
                            setReplayStatus("Skipped click: target not found or display orientation changed")
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
                            val result = if (node.isPassword || !node.isEditable) false else {
                                val args = Bundle().apply {
                                    putCharSequence(
                                        AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                                        action.inputValue ?: action.text ?: ""
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
                            } else if (coordinateFallbackAllowed(action)) {
                                setReplayStatus("Accessibility scroll unavailable; using recorded container swipe")
                                dispatchSwipe(action, ReplayPolicy.scrollForward(action.scrollDeltaY)) {
                                    waitForNextTarget(nextAction, 400L, 0L, done)
                                }
                            } else {
                                setReplayStatus("Skipped scroll: no safe recorded container bounds")
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
        ReplayPolicy.hasSemanticSelector(action)

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
        val display = realDisplaySize()

        var best: AccessibilityNodeInfo? = null
        var bestScore = Int.MIN_VALUE
        for (candidate in candidates) {
            val score = scoreNode(candidate, action, display)
            if (score > bestScore) {
                best = candidate
                bestScore = score
            }
        }

        val minimumScore = ReplayPolicy.minimumScore(action)
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
    private fun scoreNode(
        node: AccessibilityNodeInfo,
        action: RecordedAction,
        display: Pair<Int, Int>
    ): Int {
        val bounds = Rect()
        node.getBoundsInScreen(bounds)
        val snapshot = NodeSnapshot(
            text = node.text?.toString(),
            contentDescription = node.contentDescription?.toString(),
            hintText = node.hintText?.toString(),
            viewId = node.viewIdResourceName,
            className = node.className?.toString(),
            visible = node.isVisibleToUser,
            enabled = node.isEnabled,
            clickable = node.isClickable || node.isCheckable,
            editable = node.isEditable,
            scrollable = node.isScrollable,
            normalizedCenterX = bounds.exactCenterX() / display.first.toFloat(),
            normalizedCenterY = bounds.exactCenterY() / display.second.toFloat()
        )
        return ReplayPolicy.scoreNode(snapshot, action)
    }

    private fun coordinateFallbackAllowed(action: RecordedAction): Boolean =
        hasValidBounds(action) && action.displayRotation == currentDisplayRotation()

    private fun findNodeNearRecordedBounds(
        root: AccessibilityNodeInfo,
        action: RecordedAction
    ): AccessibilityNodeInfo? {
        if (!coordinateFallbackAllowed(action)) return null
        val display = realDisplaySize()
        val targetX = ((action.left + action.right) / 2f) / action.screenWidth.toFloat()
        val targetY = ((action.top + action.bottom) / 2f) / action.screenHeight.toFloat()
        val expectedLabel = action.text?.trim()?.takeIf { it.isNotBlank() }
        val candidates = mutableListOf<AccessibilityNodeInfo>()
        collectNodes(root, candidates)
        var best: AccessibilityNodeInfo? = null
        var bestDistance = Float.MAX_VALUE

        for (candidate in candidates) {
            if (!candidate.isVisibleToUser || !candidate.isEnabled) continue
            val bounds = Rect()
            candidate.getBoundsInScreen(bounds)
            if (bounds.isEmpty) continue
            val x = bounds.exactCenterX() / display.first.toFloat()
            val y = bounds.exactCenterY() / display.second.toFloat()
            val dx = targetX - x
            val dy = targetY - y
            val distance = kotlin.math.sqrt(dx * dx + dy * dy)
            if (distance > 0.045f) continue

            val actualLabels = listOfNotNull(
                candidate.text?.toString(),
                candidate.contentDescription?.toString(),
                candidate.hintText?.toString()
            ).map { it.trim() }.filter { it.isNotBlank() }
            if (expectedLabel != null && actualLabels.isNotEmpty() &&
                actualLabels.none {
                    it.equals(expectedLabel, ignoreCase = true) ||
                        it.contains(expectedLabel, ignoreCase = true) ||
                        expectedLabel.contains(it, ignoreCase = true)
                }
            ) continue

            val parent = candidate.parent
            val parentClickable = parent?.isClickable == true
            parent?.recycle()
            if (!(candidate.isClickable || candidate.isCheckable || parentClickable)) continue
            if (distance < bestDistance) {
                best?.recycle()
                best = AccessibilityNodeInfo.obtain(candidate)
                bestDistance = distance
            }
        }
        candidates.forEach { it.recycle() }
        return best
    }

    @Suppress("DEPRECATION")
    private fun realDisplaySize(): Pair<Int, Int> {
        val windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        val metrics = DisplayMetrics()
        windowManager.defaultDisplay.getRealMetrics(metrics)
        return metrics.widthPixels.coerceAtLeast(1) to metrics.heightPixels.coerceAtLeast(1)
    }

    @Suppress("DEPRECATION")
    private fun currentDisplayRotation(): Int {
        val windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        return windowManager.defaultDisplay.rotation
    }


    private fun dispatchRecordedGesture(action: RecordedAction, done: () -> Unit) {
        val display = realDisplaySize()
        val startX = ReplayPolicy.normalizedCoordinate(action.gestureStartX, display.first).toFloat()
        val startY = ReplayPolicy.normalizedCoordinate(action.gestureStartY, display.second).toFloat()
        val endX = ReplayPolicy.normalizedCoordinate(action.gestureEndX, display.first).toFloat()
        val endY = ReplayPolicy.normalizedCoordinate(action.gestureEndY, display.second).toFloat()
        val kind = action.gestureKind?.uppercase()
        val duration = action.gestureDurationMs.coerceIn(50L, 5_000L)
        val path = Path().apply {
            moveTo(startX, startY)
            if (kind == "SWIPE") lineTo(endX, endY)
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, duration))
            .build()
        val accepted = dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                setReplayStatus("ADB gesture replayed: $kind")
                handler.postDelayed(done, 200L)
            }

            override fun onCancelled(gestureDescription: GestureDescription?) {
                setReplayStatus("ADB gesture cancelled: $kind")
                done()
            }
        }, handler)
        if (!accepted) {
            setReplayStatus("ADB gesture rejected by Android")
            done()
        }
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
        val display = realDisplaySize()
        val displayWidth = display.first.coerceAtLeast(2)
        val displayHeight = display.second.coerceAtLeast(2)

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
        val display = realDisplaySize()
        val width = display.first
        val height = display.second
        val x = ReplayPolicy.scaleCoordinate((action.left + action.right) / 2, action.screenWidth, width).coerceIn(1, width - 2)
        val y = ReplayPolicy.scaleCoordinate((action.top + action.bottom) / 2, action.screenHeight, height).coerceIn(1, height - 2)
        return x.toFloat() to y.toFloat()
    }

    private fun scale(value: Int, recordedSize: Int, currentSize: Int): Int =
        ReplayPolicy.scaleCoordinate(value, recordedSize, currentSize)

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
