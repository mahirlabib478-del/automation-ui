package com.automationui

import kotlin.math.sqrt

internal data class NodeSnapshot(
    val text: String?,
    val contentDescription: String?,
    val hintText: String?,
    val viewId: String?,
    val className: String?,
    val visible: Boolean,
    val enabled: Boolean,
    val clickable: Boolean,
    val editable: Boolean,
    val scrollable: Boolean,
    val normalizedCenterX: Float,
    val normalizedCenterY: Float
)

internal object ReplayPolicy {
    fun delayMs(previousTimestamp: Long?, currentTimestamp: Long): Long {
        if (previousTimestamp == null) return 0L
        return (currentTimestamp - previousTimestamp).coerceIn(100L, 5_000L)
    }

    fun scaleCoordinate(value: Int, recordedSize: Int, currentSize: Int): Int {
        if (recordedSize <= 0 || currentSize <= 0) return value
        return ((value.toFloat() / recordedSize.toFloat()) * currentSize)
            .toInt()
            .coerceIn(0, currentSize - 1)
    }

    fun scrollForward(deltaY: Int): Boolean = deltaY >= 0

    fun hasSemanticSelector(action: RecordedAction): Boolean {
        val legacyTextWasInputValue = action.type == "SET_TEXT" && action.inputValue == null
        return !action.viewId.isNullOrBlank() ||
            (!legacyTextWasInputValue && !action.text.isNullOrBlank()) ||
            !action.contentDescription.isNullOrBlank() ||
            !action.hintText.isNullOrBlank()
    }

    fun minimumScore(action: RecordedAction): Int =
        if (hasSemanticSelector(action)) 8 else 1

    fun scoreNode(node: NodeSnapshot, action: RecordedAction): Int {
        if (!node.visible || !node.enabled) return Int.MIN_VALUE
        if (action.type == "SET_TEXT" && !node.editable) return Int.MIN_VALUE

        var score = 0
        val expectedId = action.viewId?.takeIf { it.isNotBlank() }
        val actualId = node.viewId
        val legacyTextWasInputValue = action.type == "SET_TEXT" && action.inputValue == null
        val expectedText = if (legacyTextWasInputValue) null else action.text?.trim()?.takeIf { it.isNotBlank() }
        val expectedDescription = action.contentDescription?.trim()?.takeIf { it.isNotBlank() }
        val expectedHint = action.hintText?.trim()?.takeIf { it.isNotBlank() }
        val actualText = node.text?.trim().orEmpty()
        val actualDescription = node.contentDescription?.trim().orEmpty()
        val actualHint = node.hintText?.trim().orEmpty()

        if (expectedId != null && expectedText == null &&
            expectedDescription == null && expectedHint == null && actualId != expectedId
        ) return Int.MIN_VALUE

        if (expectedId != null) score += if (actualId == expectedId) 18 else -6

        fun addTextMatch(expected: String?, actual: String, exact: Int, partial: Int) {
            if (expected == null) return
            when {
                actual.equals(expected, ignoreCase = true) -> score += exact
                actual.isNotBlank() && actual.contains(expected, ignoreCase = true) -> score += partial
                expected.isNotBlank() && actual.isNotBlank() -> score -= 18
                else -> score -= 4
            }
        }

        addTextMatch(expectedText, actualText, 28, 14)
        addTextMatch(expectedText, actualDescription, 22, 10)
        addTextMatch(expectedDescription, actualDescription, 26, 12)
        addTextMatch(expectedDescription, actualText, 20, 10)
        addTextMatch(expectedHint, actualHint, 24, 12)
        addTextMatch(expectedHint, actualText, 16, 8)

        if (!action.className.isNullOrBlank() && node.className == action.className) score += 3
        if (node.clickable) score += 3
        if (action.type == "SCROLL" && node.scrollable) score += 10
        if (action.type == "SET_TEXT" && node.editable) score += 10

        if (action.right > action.left && action.bottom > action.top &&
            action.screenWidth > 0 && action.screenHeight > 0
        ) {
            val recordedX = ((action.left + action.right) / 2f) / action.screenWidth.toFloat()
            val recordedY = ((action.top + action.bottom) / 2f) / action.screenHeight.toFloat()
            val distance = sqrt(
                (recordedX - node.normalizedCenterX) * (recordedX - node.normalizedCenterX) +
                    (recordedY - node.normalizedCenterY) * (recordedY - node.normalizedCenterY)
            )
            score += (12f - distance * 24f).toInt().coerceIn(-12, 12)
        }
        return score
    }
}
