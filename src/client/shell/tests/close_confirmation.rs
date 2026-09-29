use super::*;
use crate::api::schema::{Method, PaneTarget, TabTarget};

fn close_cases() -> [(&'static [u8], &'static str, Method); 2] {
    [
        (
            b"\x02x",
            "Close pane?",
            Method::PaneClose(PaneTarget {
                pane_id: "pane_1".into(),
            }),
        ),
        (
            b"\x02X",
            "Close tab?",
            Method::TabClose(TabTarget {
                tab_id: "tab_1".into(),
            }),
        ),
    ]
}

fn ready_state() -> ClientShellState {
    let mut state = ClientShellState::new(ClientShellConfig::from_config(&Config::default()));
    let mut snapshot = snapshot();
    let mut keep_tab = snapshot.tabs[0].clone();
    keep_tab.tab_id = "tab_keep".into();
    keep_tab.focused = false;
    let mut keep_pane = snapshot.panes[0].clone();
    keep_pane.pane_id = "pane_keep".into();
    keep_pane.tab_id = "tab_keep".into();
    keep_pane.focused = false;
    snapshot.tabs.push(keep_tab);
    snapshot.panes.push(keep_pane);
    state.set_snapshot(Box::new(snapshot));
    state.set_pane_surface(surface());
    state
}

fn click(state: &mut ClientShellState, rect: Rect, button: MouseButton) -> ClientShellInput {
    state.handle_raw_events(vec![RawInputEvent::Mouse(MouseEvent {
        kind: MouseEventKind::Down(button),
        column: rect.x + 1,
        row: rect.y,
        modifiers: KeyModifiers::empty(),
    })])
}

fn assert_close_request(outcome: &ClientShellInput, expected: &Method) {
    let [ClientShellAction::Endpoint { request, .. }] = &outcome.actions[..] else {
        panic!("confirmation should submit exactly one endpoint request");
    };
    assert_eq!(&request.method, expected);
}

#[test]
fn close_confirmation_keyboard_cancels_and_keeps_the_captured_target() {
    for (keys, title, expected) in close_cases() {
        let mut state = ready_state();
        let close = state.handle_input_bytes(keys);
        assert!(close.actions.is_empty());
        assert!(close.repaint);
        let frame = state.compose(106, 20).expect("close confirmation");
        let text = frame_rows(&frame).join("\n");
        assert!(text.contains(title));
        assert!(text.contains("Running processes"));

        let cancel = state.handle_input_bytes(b"\x1b");
        assert!(cancel.actions.is_empty());
        assert!(state.overlay.is_none());
        assert_eq!(state.mode, ClientShellMode::Terminal);

        assert!(state.handle_input_bytes(keys).actions.is_empty());
        let mut update = state.snapshot.as_deref().expect("snapshot").clone();
        let mut other_tab = update.tabs[0].clone();
        other_tab.tab_id = "tab_2".into();
        let mut other_pane = update.panes[0].clone();
        other_pane.pane_id = "pane_2".into();
        other_pane.tab_id = "tab_2".into();
        update.tabs.push(other_tab);
        update.panes.push(other_pane);
        update.focused_tab_id = Some("tab_2".into());
        update.focused_pane_id = Some("pane_2".into());
        update.workspaces[0].active_tab_id = "tab_2".into();
        for tab in &mut update.tabs {
            tab.focused = tab.tab_id == "tab_2";
        }
        for pane in &mut update.panes {
            pane.focused = pane.pane_id == "pane_2";
        }
        state.set_snapshot(Box::new(update));

        assert_close_request(&state.handle_input_bytes(b"\r"), &expected);
        assert!(state.overlay.is_none());
    }
}

#[test]
fn close_confirmation_mouse_context_menu_requires_confirmation() {
    for (_, title, expected) in close_cases() {
        let mut state = ready_state();
        state.compose(106, 20).expect("shell frame");
        let (target, action) = match &expected {
            Method::PaneClose(_) => (state.hits.panes[0].rect, ClientContextMenuAction::ClosePane),
            Method::TabClose(_) => (state.hits.tabs[0].0, ClientContextMenuAction::Close),
            _ => unreachable!(),
        };
        click(&mut state, target, MouseButton::Right);
        state.compose(106, 20).expect("context menu");
        let index = match state.overlay.as_ref() {
            Some(ClientShellOverlay::ContextMenu(menu)) => menu
                .items()
                .iter()
                .position(|item| item.action == action)
                .expect("close menu item"),
            _ => panic!("context menu should open"),
        };
        let close_item = state.hits.context_menu_rows[index].0;
        let close = click(&mut state, close_item, MouseButton::Left);
        assert!(
            close.actions.iter().all(|action| matches!(
                action,
                ClientShellAction::Endpoint { request, .. }
                    if matches!(request.method, Method::TabFocus(_))
            )),
            "{title}: {:?}",
            close.actions
        );
        let frame = state.compose(106, 20).expect("close confirmation");
        assert!(frame_rows(&frame).join("\n").contains(title));

        let confirm = state.hits.overlay_primary;
        assert_close_request(&click(&mut state, confirm, MouseButton::Left), &expected);
        assert!(state.overlay.is_none());
    }
}

#[test]
fn close_confirmation_mouse_cancel_preserves_the_terminal() {
    for (keys, _, _) in close_cases() {
        let mut state = ready_state();
        assert!(state.handle_input_bytes(keys).actions.is_empty());
        state.compose(106, 20).expect("close confirmation");
        let cancel = state.hits.overlay_cancel;
        assert!(click(&mut state, cancel, MouseButton::Left)
            .actions
            .is_empty());
        assert!(state.overlay.is_none());
        assert_eq!(state.mode, ClientShellMode::Terminal);
        assert_eq!(state.snapshot.as_deref().expect("snapshot").panes.len(), 2);
    }
}

#[test]
fn close_confirmation_can_be_disabled_for_panes_and_tabs() {
    for (keys, _, expected) in close_cases() {
        let mut state = ready_state();
        state.config.confirm_close = false;
        assert_close_request(&state.handle_input_bytes(keys), &expected);
        assert!(state.overlay.is_none());
    }
}

#[test]
fn close_confirmation_rejects_reused_ids_after_a_server_restart() {
    for (keys, _, _) in close_cases() {
        let mut state = ready_state();
        assert!(state.handle_input_bytes(keys).actions.is_empty());
        let mut restarted = state.snapshot.as_deref().unwrap().clone();
        restarted.boot_id.push_str("-restarted");
        state.set_snapshot(Box::new(restarted));
        assert!(state.handle_input_bytes(b"\r").actions.is_empty());
    }
}

#[test]
fn close_confirmation_rejects_targets_from_an_old_connection() {
    for (keys, _, _) in close_cases() {
        let mut state = ready_state();
        assert!(state.handle_input_bytes(keys).actions.is_empty());
        state.endpoints[0].snapshot_generation = Some(2);
        assert!(state.handle_input_bytes(b"\r").actions.is_empty());
    }
}
