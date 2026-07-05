package com.ticketbox.ui.components

/**
 * Builds a stable single-select tag option list for filter controls.
 *
 * The selected tag is pinned before applying [limit] so stale or long-tail
 * selections remain visible even when the available list is truncated.
 */
fun buildAppTagFilterChoices(
    availableTags: List<String>,
    selectedTag: String,
    limit: Int? = null,
): List<String> {
    val selected = selectedTag.trim()
    val choices = linkedMapOf<String, String>()
    if (selected.isNotBlank()) {
        choices[selected.lowercase()] = selected
    }
    availableTags.forEach { raw ->
        val tag = raw.trim()
        if (tag.isNotBlank()) {
            choices.putIfAbsent(tag.lowercase(), tag)
        }
    }
    val normalizedLimit = limit?.coerceAtLeast(0) ?: choices.size
    return choices.values.take(normalizedLimit)
}
