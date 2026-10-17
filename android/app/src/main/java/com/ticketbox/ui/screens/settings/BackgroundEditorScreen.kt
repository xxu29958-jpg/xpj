package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.DialogWindowProvider
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.BackgroundTransform
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.appearance.background.BackgroundPreviewStage
import com.ticketbox.ui.appearance.background.BackgroundTransformGeometry
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.appearance.background.rememberBackgroundImage
import com.ticketbox.ui.components.AppButtonIcons
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.theme.configureTicketboxSystemBars
import com.ticketbox.viewmodel.BackgroundEditorState
import androidx.compose.material.icons.filled.Crop
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.material3.IconButton
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import com.ticketbox.ui.components.AppAccountButton
import com.ticketbox.ui.components.AppDomainHeader

/**
 * 独立的全窗口编辑面，不继承设置页或安全提示横幅扣减后的内容高度。
 * 舞台和全局背景使用相同画布，系统栏 inset 只作用于浮动控件。
 * 草稿、保存和取消仍由 AppearanceViewModel 拥有；没有第二套编辑状态。
 */
@Composable
internal fun BackgroundEditorScreen(
    editor: BackgroundEditorState,
    currentSkin: AppSkin,
    actions: BackgroundEditorActions,
) {
    Dialog(
        onDismissRequest = actions.onCancel,
        properties = DialogProperties(
            usePlatformDefaultWidth = false,
            decorFitsSystemWindows = false,
            dismissOnBackPress = !editor.saving,
            dismissOnClickOutside = false,
        ),
    ) {
        BackgroundEditorContent(editor, currentSkin, actions)
    }
}

@Composable
private fun BackgroundEditorContent(
    editor: BackgroundEditorState,
    currentSkin: AppSkin,
    actions: BackgroundEditorActions,
) {
    val view = LocalView.current
    SideEffect {
        configureTicketboxSystemBars((view.parent as DialogWindowProvider).window, view, currentSkin)
    }
    val draft = editor.settings
    var previewRole by remember { mutableStateOf(SurfaceRole.Ledger) }
    var composing by rememberSaveable { mutableStateOf(false) }
    Box(modifier = Modifier.fillMaxSize()) {
        BackgroundEditorStage(
            draft = draft,
            skin = currentSkin,
            role = previewRole,
            gestures = BackgroundEditorGestures(
                enabled = composing && !editor.saving,
                onTransformChange = { transform -> actions.onDraftChange(draft.copy(transform = transform)) },
            ),
        ) {
            if (!composing) {
                Column(modifier = Modifier.fillMaxSize()) {
                    // The preview is the real page top: a root header opens the same photo window as the shell.
                    Column(
                        modifier = Modifier.weight(1f).verticalScroll(rememberScrollState()),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
                    ) {
                        BackgroundEditorPagePreview(previewRole)
                        BackgroundReadabilitySample(Modifier.padding(horizontal = AppSpacing.screenHorizontal))
                    }
                    BackgroundEditorControlPanel(
                        editor = editor,
                        previewRole = previewRole,
                        onPreviewRole = { previewRole = it },
                        onCompose = { composing = true },
                        actions = actions,
                    )
                }
            }
        }
        if (composing) {
            BackgroundEditorCompositionPanel(editor, actions, onDone = { composing = false },
                modifier = Modifier.align(Alignment.BottomCenter))
        }
    }
}

internal data class BackgroundEditorActions(
    val onDraftChange: (BackgroundSettings) -> Unit,
    val onCancel: () -> Unit,
    val onApply: () -> Unit,
)

/** 编辑器预览的页面角色抽样：覆盖用户最常看背景的五个面，Today/Auth 由真实页面验收。 */
private val backgroundEditorPreviewRoles = listOf(
    SurfaceRole.Pending,
    SurfaceRole.Ledger,
    SurfaceRole.Stats,
    SurfaceRole.Edit,
    SurfaceRole.Settings,
)

/**
 * 全屏预览舞台：真实三层渲染（[BackgroundPreviewStage]）+ 拖捏手势。
 * 与 renderer 同一 geometry 单源；视差 1.01–1.05 的额外缩放在手势闭环
 * （拖到边界即收敛）下不可感知，不重复计入。
 */
private class BackgroundEditorGestures(val enabled: Boolean, val onTransformChange: (BackgroundTransform) -> Unit)

@Composable
private fun BackgroundEditorStage(
    draft: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
    gestures: BackgroundEditorGestures,
    content: @Composable BoxScope.() -> Unit,
) {
    val gesturesEnabled = gestures.enabled
    val onTransformChange = gestures.onTransformChange
    val customPath = draft.customImagePath
        ?.takeIf { draft.source == BackgroundSource.CustomImage }
    val imageSize = rememberBackgroundImage(customPath)?.size ?: IntSize.Zero
    var viewportSize by remember { mutableStateOf(IntSize.Zero) }
    val currentDraft by rememberUpdatedState(draft)
    val currentOnTransformChange by rememberUpdatedState(onTransformChange)
    val canGesture = gesturesEnabled && imageSize != IntSize.Zero
    Box(
        modifier = Modifier
            .fillMaxSize()
            .testTag("background-editor-viewport")
            .onSizeChanged { viewportSize = it }
            .then(
                if (canGesture) {
                    Modifier.pointerInput(imageSize) {
                        detectTransformGestures { _, pan, zoom, _ ->
                            val zoomed = BackgroundTransformGeometry.zoomed(
                                currentDraft.transform,
                                zoom,
                            )
                            val panned = BackgroundTransformGeometry.panned(
                                current = zoomed,
                                panPx = pan,
                                viewport = viewportSize,
                                image = imageSize,
                            )
                            if (panned != currentDraft.transform) {
                                currentOnTransformChange(panned)
                            }
                        }
                    }
                } else {
                    Modifier
                },
            ),
    ) {
        BackgroundPreviewStage(
            settings = draft,
            skin = skin,
            role = role,
            modifier = Modifier.fillMaxSize(),
            content = content,
        )
    }
}

@Composable
private fun BackgroundEditorHeading(
    draft: BackgroundSettings,
    onBack: () -> Unit,
    enabled: Boolean,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = onBack, enabled = enabled) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.background_editor_back))
        }
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(stringResource(R.string.background_editor_page_title), style = MaterialTheme.typography.titleLarge)
            Text(stringResource(
                if (draft.source == BackgroundSource.BuiltIn) R.string.background_editor_preview_builtin
                else R.string.background_editor_preview_source,
                backgroundSourceLabel(draft),
            ), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Root roles preview the real domain header; editing and settings pages have no photo window. */
@Composable
private fun BackgroundEditorPagePreview(role: SurfaceRole) {
    val title = when (role) {
        SurfaceRole.Pending -> R.string.nav_domain_inbox
        SurfaceRole.Ledger -> R.string.nav_domain_transactions
        SurfaceRole.Stats -> R.string.nav_domain_insights
        else -> null
    }
    if (title == null) {
        Spacer(Modifier.statusBarsPadding())
        return
    }
    val description = stringResource(R.string.background_editor_page_preview, stringResource(title))
    AppDomainHeader(
        title = stringResource(title),
        modifier = Modifier.clearAndSetSemantics { contentDescription = description },
    ) {
        Icon(ImageVector.vectorResource(R.drawable.ic_lucide_plus), contentDescription = null,
            modifier = Modifier.padding(AppSpacing.compactGap))
        AppAccountButton(onClick = {})
    }
}

/**
 * One bottom panel owns every choice and the single commit, so the photo stays visible above it.
 * Preview page and immersion are chips: one tap compares the real result instead of a menu.
 */
@Composable
private fun BackgroundEditorControlPanel(
    editor: BackgroundEditorState,
    previewRole: SurfaceRole,
    onPreviewRole: (SurfaceRole) -> Unit,
    onCompose: () -> Unit,
    actions: BackgroundEditorActions,
) {
    val draft = editor.settings
    val maxPanelHeight = LocalConfiguration.current.screenHeightDp.dp * 0.62f
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(topStart = AppRadius.large, topEnd = AppRadius.large),
        color = MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.opaque),
    ) {
        Column(
            modifier = Modifier
                .heightIn(max = maxPanelHeight)
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(horizontal = AppSpacing.screenHorizontal, vertical = AppSpacing.contentGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            BackgroundEditorHeading(draft, actions.onCancel, !editor.saving)
            AppStatusBanner(message = editor.message, tone = MessageTone.Danger)
            BackgroundEditorChips(
                label = stringResource(R.string.background_editor_section_preview_role),
                items = backgroundEditorPreviewRoles.map { AppSegmentedItem(it, stringResource(backgroundEditorRoleNameRes(it)), !editor.saving) },
                selected = previewRole,
                onSelect = onPreviewRole,
            )
            BackgroundEditorChips(
                label = stringResource(R.string.appearance_section_immersion_title),
                items = ImmersionMode.entries.map { AppSegmentedItem(it, stringResource(immersionModeNameRes(it)), !editor.saving) },
                selected = draft.immersionMode,
                onSelect = { actions.onDraftChange(draft.copy(immersionMode = it)) },
                note = stringResource(immersionModeDescriptionRes(draft.immersionMode)),
            )
            if (draft.source == BackgroundSource.CustomImage) {
                AppOutlinedButton(onClick = onCompose, modifier = Modifier.fillMaxWidth(),
                    options = AppOutlinedButtonOptions(enabled = !editor.saving)) {
                    Icon(Icons.Filled.Crop, contentDescription = null, modifier = Modifier.padding(end = AppSpacing.smallGap))
                    Text(stringResource(R.string.background_editor_gesture_mode))
                }
            }
            Text(stringResource(R.string.background_editor_scope_note),
                color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            AppPrimaryButton(
                text = stringResource(if (editor.saving) R.string.background_editor_applying else R.string.background_editor_apply_button),
                icons = AppButtonIcons(leading = Icons.Filled.Check),
                modifier = Modifier.fillMaxWidth(),
                enabled = !editor.saving,
                onClick = actions.onApply,
            )
            TextButton(enabled = !editor.saving, onClick = actions.onCancel, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                Text(stringResource(R.string.background_editor_cancel_button))
            }
        }
    }
}

@Composable
private fun <T : Any> BackgroundEditorChips(
    label: String,
    items: List<AppSegmentedItem<T>>,
    selected: T,
    onSelect: (T) -> Unit,
    note: String? = null,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        AppSegmentedControl(options = items, selectedValue = selected, onValueChange = onSelect)
        note?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}

/** Composition exposes the unchanged full-window gesture canvas and its accessible button alternatives. */
@Composable
private fun BackgroundEditorCompositionPanel(
    editor: BackgroundEditorState,
    actions: BackgroundEditorActions,
    onDone: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val maxPanelHeight = LocalConfiguration.current.screenHeightDp.dp * 0.56f
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(topStart = AppRadius.large, topEnd = AppRadius.large),
        color = MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.opaque),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(max = maxPanelHeight)
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(AppSpacing.contentGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(stringResource(R.string.background_editor_gesture_mode), style = MaterialTheme.typography.titleMedium)
            BackgroundEditorCompositionControls(
                transform = editor.settings.transform,
                enabled = !editor.saving,
                onTransformChange = { actions.onDraftChange(editor.settings.copy(transform = it)) },
            )
            AppPrimaryButton(text = stringResource(R.string.background_editor_composition_done),
                icons = AppButtonIcons(leading = Icons.Filled.Check), modifier = Modifier.fillMaxWidth(), enabled = !editor.saving, onClick = onDone)
        }
    }
}
