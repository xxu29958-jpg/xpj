package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.graphics.vector.ImageVector
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.BackgroundTransform
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.appearance.background.BackgroundPreviewStage
import com.ticketbox.ui.appearance.background.BackgroundTransformGeometry
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.appearance.background.rememberBackgroundImage
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.BackgroundEditorState

/**
 * 全局背景编辑面（visual-ledger 全局背景批）：**真正全屏编辑**。
 *
 * 诚实构图预览的退出门：预览舞台铺满整个编辑窗口（WORKSPACE 路由无顶栏、
 * 二级页激活时无底部主导航，content innerPadding 为 0），与全局
 * ImmersiveBackgroundScaffold 的渲染区域同为整个 Compose 画布——renderer 的
 * BoxWithConstraints 拿到的就是真实 viewport，cover 构图与主页面像素级一致；
 * 系统栏 inset 只垫给浮动 chrome（顶部栏 / 控制面板），绝不垫给舞台，避免
 * 「编辑面扣完栏再换 crop」。旧 0.42 屏高小舞台宽高比不同，用户选定的主体
 * 在 Apply 后会被另裁，已退役。
 *
 * 产品语言与 Web 编辑面一致：真实渲染管线全屏实时预览 + 底部浮动控制条。
 * draft / saving / message 全部由 AppearanceViewModel 唯一拥有：本屏只回调，
 * 不持有文件、不持有可能丢失的本地草稿。取消无副作用，应用在 VM 发布成功后
 * editor 置空，导航随之回外观页。
 */
@Composable
internal fun BackgroundEditorScreen(
    editor: BackgroundEditorState,
    currentSkin: AppSkin,
    actions: BackgroundEditorActions,
) {
    val draft = editor.settings
    var previewRole by remember { mutableStateOf(SurfaceRole.Ledger) }
    Box(modifier = Modifier.fillMaxSize()) {
        BackgroundEditorStage(
            draft = draft,
            skin = currentSkin,
            role = previewRole,
            gesturesEnabled = !editor.saving,
            onTransformChange = { transform ->
                actions.onDraftChange(draft.copy(transform = transform))
            },
        )
        BackgroundEditorTopBar(
            onBack = actions.onCancel,
            enabled = !editor.saving,
            modifier = Modifier.align(Alignment.TopStart),
        )
        BackgroundEditorStageCaption(
            modifier = Modifier.align(Alignment.TopCenter),
        )
        BackgroundEditorControlPanel(
            editor = editor,
            previewRole = previewRole,
            onRoleSelect = { previewRole = it },
            actions = actions,
            modifier = Modifier.align(Alignment.BottomCenter),
        )
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
        )
    }
}

/** 顶部浮动栏：返回（= 取消，VM 丢弃 draft 与候选文件）+ 标题，半透明 chip 保可读。 */
@Composable
private fun BackgroundEditorTopBar(
    onBack: () -> Unit,
    enabled: Boolean,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .statusBarsPadding()
            .padding(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(
            onClick = onBack,
            enabled = enabled,
            modifier = Modifier
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.heavy)),
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(R.string.background_editor_cancel_button),
            )
        }
        Text(
            text = stringResource(R.string.background_editor_page_title),
            modifier = Modifier
                .padding(start = AppSpacing.smallGap)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.heavy))
                .padding(
                    horizontal = AppSpacing.compactGap,
                    vertical = AppSpacing.smallGap,
                ),
            style = MaterialTheme.typography.titleMedium,
        )
    }
}

@Composable
private fun BackgroundEditorStageCaption(
    modifier: Modifier = Modifier,
) {
    Text(
        text = stringResource(R.string.background_editor_stage_caption),
        modifier = modifier
            .statusBarsPadding()
            // 顶栏高度 = 48dp 触控 + 上下 smallGap；caption 贴在其下，不与标题重叠。
            .padding(top = AppSpacing.controlMinHeight + AppSpacing.smallGap * 2)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.heavy))
            .padding(
                horizontal = AppSpacing.compactGap,
                vertical = AppSpacing.tinyGap,
            ),
        style = MaterialTheme.typography.labelSmall,
    )
}

/**
 * 底部控制面板：角色抽样 / 构图 / 沉浸 / 取消应用。近实心 surface 保证控件
 * 自身可读（控件不是被预览对象）；面板可滚动，小屏不挤掉按钮。
 */
@Composable
private fun BackgroundEditorControlPanel(
    editor: BackgroundEditorState,
    previewRole: SurfaceRole,
    onRoleSelect: (SurfaceRole) -> Unit,
    actions: BackgroundEditorActions,
    modifier: Modifier = Modifier,
) {
    val draft = editor.settings
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
            AppStatusBanner(message = editor.message, tone = MessageTone.Danger)
            BackgroundEditorPanelLabel(text = stringResource(R.string.background_editor_section_preview_role))
            AppCompactChips {
                FlowRow(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                ) {
                    backgroundEditorPreviewRoles.forEach { role ->
                        AppFilterChip(
                            label = stringResource(backgroundEditorRoleNameRes(role)),
                            selected = previewRole == role,
                            onClick = { onRoleSelect(role) },
                        )
                    }
                }
            }
            if (draft.source == BackgroundSource.CustomImage) {
                BackgroundEditorPanelLabel(text = stringResource(R.string.background_editor_section_composition))
                BackgroundEditorCompositionControls(
                    transform = draft.transform,
                    enabled = !editor.saving,
                    onTransformChange = { transform ->
                        actions.onDraftChange(draft.copy(transform = transform))
                    },
                )
            }
            BackgroundEditorPanelLabel(text = stringResource(R.string.appearance_section_immersion_title))
            ImmersionModePicker(
                selected = draft.immersionMode,
                onSelect = { mode -> actions.onDraftChange(draft.copy(immersionMode = mode)) },
            )
            Text(
                text = stringResource(R.string.background_editor_scope_note),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                AppSecondaryButton(
                    text = stringResource(R.string.background_editor_cancel_button),
                    modifier = Modifier.weight(1f),
                    enabled = !editor.saving,
                    onClick = actions.onCancel,
                )
                AppPrimaryButton(
                    text = stringResource(
                        if (editor.saving) {
                            R.string.background_editor_applying
                        } else {
                            R.string.background_editor_apply_button
                        },
                    ),
                    icon = Icons.Filled.Check,
                    modifier = Modifier.weight(1f),
                    enabled = !editor.saving,
                    onClick = actions.onApply,
                )
            }
        }
    }
}

@Composable
private fun BackgroundEditorPanelLabel(
    text: String,
) {
    Text(
        text = text,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.labelLarge,
    )
}

/**
 * 构图控制：缩放 +/-、四向微调（水平/竖直均可点按，不只三档）、三档 anchor
 * 快捷与重置。全部换算走 [BackgroundTransformGeometry]，不猜像素。
 */
@Composable
private fun BackgroundEditorCompositionControls(
    transform: BackgroundTransform,
    enabled: Boolean,
    onTransformChange: (BackgroundTransform) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        BackgroundActionButton(
            text = stringResource(R.string.background_editor_zoom_out),
            modifier = Modifier.weight(1f),
            enabled = enabled && transform.scale > BackgroundTransformGeometry.MIN_SCALE,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.zoomed(transform, 1f / BackgroundTransformGeometry.ZOOM_STEP),
                )
            },
        )
        BackgroundActionButton(
            text = stringResource(R.string.background_editor_reset),
            modifier = Modifier.weight(1f),
            enabled = enabled && transform != BackgroundTransform(),
            onClick = { onTransformChange(BackgroundTransform()) },
        )
        BackgroundActionButton(
            text = stringResource(R.string.background_editor_zoom_in),
            modifier = Modifier.weight(1f),
            enabled = enabled && transform.scale < BackgroundTransformGeometry.MAX_SCALE,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.zoomed(transform, BackgroundTransformGeometry.ZOOM_STEP),
                )
            },
        )
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap, Alignment.CenterHorizontally),
    ) {
        BackgroundEditorNudgeButton(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
            contentDescription = stringResource(R.string.background_editor_nudge_left),
            enabled = enabled,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.nudged(transform, -BackgroundTransformGeometry.OFFSET_STEP, 0f),
                )
            },
        )
        BackgroundEditorNudgeButton(
            imageVector = Icons.Filled.KeyboardArrowUp,
            contentDescription = stringResource(R.string.background_editor_nudge_up),
            enabled = enabled,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.nudged(transform, 0f, -BackgroundTransformGeometry.OFFSET_STEP),
                )
            },
        )
        BackgroundEditorNudgeButton(
            imageVector = Icons.Filled.KeyboardArrowDown,
            contentDescription = stringResource(R.string.background_editor_nudge_down),
            enabled = enabled,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.nudged(transform, 0f, BackgroundTransformGeometry.OFFSET_STEP),
                )
            },
        )
        BackgroundEditorNudgeButton(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = stringResource(R.string.background_editor_nudge_right),
            enabled = enabled,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.nudged(transform, BackgroundTransformGeometry.OFFSET_STEP, 0f),
                )
            },
        )
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        AppFilterChip(
            modifier = Modifier.weight(1f),
            label = stringResource(R.string.background_editor_anchor_top),
            selected = transform.offsetY <= -1f + 0.01f,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.clamped(transform.copy(offsetY = -1f)),
                )
            },
        )
        AppFilterChip(
            modifier = Modifier.weight(1f),
            label = stringResource(R.string.background_editor_anchor_center),
            selected = kotlin.math.abs(transform.offsetY) < 0.01f,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.clamped(transform.copy(offsetY = 0f)),
                )
            },
        )
        AppFilterChip(
            modifier = Modifier.weight(1f),
            label = stringResource(R.string.background_editor_anchor_bottom),
            selected = transform.offsetY >= 1f - 0.01f,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.clamped(transform.copy(offsetY = 1f)),
                )
            },
        )
    }
}

@Composable
private fun BackgroundEditorNudgeButton(
    imageVector: ImageVector,
    contentDescription: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    IconButton(onClick = onClick, enabled = enabled) {
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(
                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = AppAlpha.medium),
                )
                .padding(AppSpacing.smallGap),
        ) {
            Icon(imageVector = imageVector, contentDescription = contentDescription)
        }
    }
}
