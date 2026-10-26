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
