package com.automationui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReplayPolicyTest {
    private fun action(
        type: String = "CLICK",
        timestamp: Long = 1_000L,
        inputValue: String? = null,
        text: String? = null,
        viewId: String? = null,
        left: Int = 100,
        top: Int = 200,
        right: Int = 200,
        bottom: Int = 260,
        screenWidth: Int = 1_000,
        screenHeight: Int = 2_000
    ) = RecordedAction(
        type = type,
        packageName = "com.example",
        text = text,
        viewId = viewId,
        contentDescription = null,
        className = null,
        left = left,
        top = top,
        right = right,
        bottom = bottom,
        screenWidth = screenWidth,
        screenHeight = screenHeight,
        scrollDeltaY = 0,
        timestamp = timestamp,
        inputValue = inputValue
    )

    @Test fun firstActionHasNoArtificialDelay() {
        assertEquals(0L, ReplayPolicy.delayMs(null, 5_000L))
    }

    @Test fun actionDelayIsBounded() {
        assertEquals(100L, ReplayPolicy.delayMs(1_000L, 1_010L))
        assertEquals(5_000L, ReplayPolicy.delayMs(1_000L, 20_000L))
        assertEquals(500L, ReplayPolicy.delayMs(1_000L, 1_500L))
    }

    @Test fun coordinatesScaleAndClampToDisplay() {
        assertEquals(500, ReplayPolicy.scaleCoordinate(250, 500, 1_000))
        assertEquals(999, ReplayPolicy.scaleCoordinate(500, 500, 1_000))
        assertEquals(250, ReplayPolicy.scaleCoordinate(250, 0, 1_000))
    }

    @Test fun scrollDirectionIsStable() {
        assertTrue(ReplayPolicy.scrollForward(200))
        assertTrue(ReplayPolicy.scrollForward(0))
        assertFalse(ReplayPolicy.scrollForward(-200))
    }

    @Test fun setTextValueIsNotUsedAsAFieldSelectorForLegacyActions() {
        val legacy = action(type = "SET_TEXT", text = "a typed value", inputValue = null, viewId = null)
        assertFalse(ReplayPolicy.hasSemanticSelector(legacy))
    }

    @Test fun inputValueDoesNotPreventMatchingByFieldId() {
        val textAction = action(type = "SET_TEXT", inputValue = "new value", text = "Search", viewId = "app:id/search")
        val snapshot = NodeSnapshot(
            text = "old value",
            contentDescription = null,
            hintText = "Search",
            viewId = "app:id/search",
            className = "android.widget.EditText",
            visible = true,
            enabled = true,
            clickable = true,
            editable = true,
            scrollable = false,
            normalizedCenterX = 0.15f,
            normalizedCenterY = 0.115f
        )
        assertTrue(ReplayPolicy.scoreNode(snapshot, textAction) >= ReplayPolicy.minimumScore(textAction))
    }

    @Test fun normalizedGestureCoordinatesScaleToCurrentDisplay() {
        assertEquals(0, ReplayPolicy.normalizedCoordinate(0, 1080))
        assertEquals(539, ReplayPolicy.normalizedCoordinate(5000, 1080))
        assertEquals(1079, ReplayPolicy.normalizedCoordinate(10000, 1080))
        assertEquals(0, ReplayPolicy.normalizedCoordinate(5000, 0))
    }

    @Test fun unknownGestureRotationIsAllowedButKnownMismatchIsBlocked() {
        assertTrue(ReplayPolicy.gestureRotationMatches(-1, 1))
        assertTrue(ReplayPolicy.gestureRotationMatches(1, 1))
        assertFalse(ReplayPolicy.gestureRotationMatches(0, 1))
    }

    private fun gesture(
        timestamp: Long,
        kind: String,
        x: Int = 5000,
        y: Int = 5000,
        endX: Int = x,
        endY: Int = y
    ) = RecordedAction(
        type = "GESTURE", packageName = null, text = "ADB captured $kind",
        viewId = null, contentDescription = null, className = null,
        left = 0, top = 0, right = 0, bottom = 0,
        screenWidth = 1080, screenHeight = 2400, scrollDeltaY = endY - y,
        timestamp = timestamp, displayRotation = 0, gestureKind = kind,
        gestureStartX = x, gestureStartY = y, gestureEndX = endX, gestureEndY = endY,
        gestureDurationMs = 250
    )

    @Test fun gestureSchemaRejectsMissingCoordinatesAndAcceptsValidGesture() {
        assertTrue(isValidGesture(gesture(1000, "TAP")))
        assertFalse(isValidGesture(gesture(1000, "UNKNOWN")))
        assertFalse(isValidGesture(gesture(1000, "SWIPE").copy(gestureEndX = -1)))
    }

    @Test fun mergeRemovesTapAlreadyCapturedAsSemanticClick() {
        val click = action(
            type = "CLICK", timestamp = 2_000L, text = "Continue",
            left = 450, top = 900, right = 550, bottom = 1_100,
            screenWidth = 1_000, screenHeight = 2_000
        )
        val tap = gesture(2_500L, "TAP", x = 5000, y = 5000)
        val merged = mergeRecordedActions(listOf(click), listOf(tap))
        assertEquals(1, merged.size)
        assertEquals("CLICK", merged.single().type)
    }

    @Test fun mergeRemovesGestureThatAlreadyTriggeredHome() {
        val home = action(type = "HOME", timestamp = 10_100L).copy(
            left = 0, top = 0, right = 0, bottom = 0
        )
        val homeSwipe = gesture(10_000L, "SWIPE", x = 5000, y = 9800, endX = 5000, endY = 5000)
        val merged = mergeRecordedActions(listOf(home), listOf(homeSwipe))
        assertEquals(1, merged.size)
        assertEquals("HOME", merged.single().type)
    }

    @Test fun mergeRemovesEdgeSwipeThatAlreadyTriggeredBack() {
        val back = action(type = "BACK", timestamp = 20_100L).copy(
            left = 0, top = 0, right = 0, bottom = 0
        )
        val backSwipe = gesture(20_000L, "SWIPE", x = 100, y = 5000, endX = 2500, endY = 5000)
        val merged = mergeRecordedActions(listOf(back), listOf(backSwipe))
        assertEquals(1, merged.size)
        assertEquals("BACK", merged.single().type)
    }

    @Test fun mergeKeepsGestureWhenNoSemanticActionMatches() {
        val swipe = gesture(10_000L, "SWIPE", x = 5000, y = 8000, endX = 5000, endY = 2000)
        val merged = mergeRecordedActions(emptyList(), listOf(swipe))
        assertEquals(1, merged.size)
        assertEquals("GESTURE", merged.single().type)
    }

    @Test fun setTextWillNeverSelectANonEditableNode() {
        val textAction = action(type = "SET_TEXT", inputValue = "new value", viewId = "app:id/search")
        val snapshot = NodeSnapshot(
            text = "",
            contentDescription = null,
            hintText = null,
            viewId = "app:id/search",
            className = "android.widget.TextView",
            visible = true,
            enabled = true,
            clickable = true,
            editable = false,
            scrollable = false,
            normalizedCenterX = 0.15f,
            normalizedCenterY = 0.115f
        )
        assertEquals(Int.MIN_VALUE, ReplayPolicy.scoreNode(snapshot, textAction))
    }
}
