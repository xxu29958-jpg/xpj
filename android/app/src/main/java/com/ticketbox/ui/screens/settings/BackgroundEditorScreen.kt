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
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
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
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.asTextStyle
import com.ticketbox.ui.theme.configureTicketboxSystemBars
import com.ticketbox.viewmodel.BackgroundEditorState

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
            gesturesEnabled = composing && !editor.saving,
            onTransformChange = { transform ->
                actions.onDraftChange(draft.copy(transform = transform))
            },
        )
        if (composing) {
            BackgroundEditorCompositionPanel(editor, actions, onDone = { composing = false },
                modifier = Modifier.align(Alignment.BottomCenter))
        } else {
            Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()) {
                Column(
                    Modifier.weight(1f).verticalScroll(rememberScrollState())
                        .padding(horizontal = AppSpacing.screenHorizontal, vertical = AppSpacing.contentGap),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
                ) {
                    BackgroundEditorHeading(actions.onCancel, !editor.saving)
                    AppStatusBanner(message = editor.message, tone = MessageTone.Danger)
                    BackgroundReadabilitySample()
                    BackgroundEditorChoice(
                        label = stringResource(R.string.background_editor_section_preview_role),
                        choices = backgroundEditorPreviewRoles.map { stringResource(backgroundEditorRoleNameRes(it)) },
                        selectedIndex = backgroundEditorPreviewRoles.indexOf(previewRole),
                        enabled = !editor.saving,
                        onSelect = { previewRole = backgroundEditorPreviewRoles[it] },
                    )
                    BackgroundEditorCompositionEntry(editor, onOpen = { composing = true })
                    BackgroundEditorChoice(
                        label = stringResource(R.string.appearance_section_immersion_title),
                        choices = ImmersionMode.entries.map { stringResource(immersionModeNameRes(it)) },
                        selectedIndex = ImmersionMode.entries.indexOf(draft.immersionMode),
                        enabled = !editor.saving,
                        onSelect = { actions.onDraftChange(draft.copy(immersionMode = ImmersionMode.entries[it])) },
                    )
                    Text(stringResource(R.string.background_editor_scope_note),
                        color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                }
                Surface(color = MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.opaque)) {
                    Box(Modifier.padding(horizontal = AppSpacing.screenHorizontal, vertical = AppSpacing.contentGap)) {
                        BackgroundEditorFooter(editor.saving, actions)
                    }
                }
            }
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
@Composable
private fun BackgroundEditorStage(
    draft: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
    gesturesEnabled: Boolean,
    onTransformChange: (BackgroundTransform) -> Unit,
) {
    val customPath = draft.customImagePath
        ?.takeIf { draft.source == BackgroundSource.CustomImage }
    val bitmap = rememberBackgroundImage(customPath)
    val imageSize = bitmap?.let { IntSize(it.width, it.height) } ?: IntSize.Zero
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
        ) {}
    }
}

@Composable
private fun BackgroundEditorHeading(
    onBack: () -> Unit,
    enabled: Boolean,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap)) {
        TextButton(onClick = onBack, enabled = enabled) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null)
            Text(stringResource(R.string.background_editor_back), modifier = Modifier.padding(start = AppSpacing.smallGap))
        }
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(stringResource(R.string.background_editor_page_title),
                style = AppTextHierarchy.hero.asTextStyle())
            Text(stringResource(R.string.background_editor_intro), style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun BackgroundEditorChoice(
    label: String,
    choices: List<String>,
    selectedIndex: Int,
    enabled: Boolean,
    onSelect: (Int) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Box {
            Surface(onClick = { expanded = true }, enabled = enabled,
                modifier = Modifier.fillMaxWidth().semantics { contentDescription = label },
                shape = RoundedCornerShape(14.dp)) {
                Row(Modifier.heightIn(min = 52.dp).padding(AppSpacing.compactPadding),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text(choices[selectedIndex], modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
                    Icon(Icons.Filled.KeyboardArrowDown, contentDescription = null)
                }
            }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                choices.forEachIndexed { index, choice ->
                    DropdownMenuItem(text = { Text(choice) }, enabled = enabled,
                        onClick = { expanded = false; onSelect(index) })
                }
            }
        }
    }
}

@Composable
private fun BackgroundEditorCompositionEntry(editor: BackgroundEditorState, onOpen: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(stringResource(R.string.background_editor_section_composition), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Surface(onClick = onOpen, enabled = !editor.saving && editor.settings.source == BackgroundSource.CustomImage,
            modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp)) {
            Row(Modifier.heightIn(min = 52.dp).padding(AppSpacing.compactPadding), verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(if (editor.settings.source == BackgroundSource.CustomImage) R.string.background_editor_gesture_mode
                    else R.string.background_editor_composition_builtin), modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
                Icon(Icons.Filled.KeyboardArrowDown, contentDescription = null)
            }
        }
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

@Composable
private fun BackgroundEditorFooter(
    saving: Boolean,
    actions: BackgroundEditorActions,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        TextButton(enabled = !saving, onClick = actions.onCancel) {
            Text(stringResource(R.string.background_editor_cancel_button))
        }
        AppPrimaryButton(
            text = stringResource(
                if (saving) {
                    R.string.background_editor_applying
                } else {
                    R.string.background_editor_apply_button
                },
            ),
            icons = AppButtonIcons(leading = Icons.Filled.Check),
            modifier = Modifier.weight(1f),
            enabled = !saving,
            onClick = actions.onApply,
        )
    }
}
