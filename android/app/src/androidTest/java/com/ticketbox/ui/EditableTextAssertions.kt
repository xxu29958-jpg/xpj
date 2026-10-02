package com.ticketbox.ui

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.assert
import androidx.compose.ui.text.AnnotatedString

/** Compare the original editable value exactly, independently of its label and other decoration. */
internal fun SemanticsNodeInteraction.assertEditableTextEquals(expected: String): SemanticsNodeInteraction =
    assert(SemanticsMatcher.expectValue(SemanticsProperties.EditableText, AnnotatedString(expected)))
