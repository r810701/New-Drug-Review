# -*- coding: utf-8 -*-
"""
modules/auth.py
================
輕量級角色權限管理（Role-Based Access）。

正式上線建議接院內 SSO / AD，這裡先提供一個可運作、資料存在本機 JSON
的最小實作，介面設計上刻意讓 `current_user()` / `require_role()` 這類
呼叫方式不需要更動，未來要換成真正的驗證後端時，只需要改寫本檔案內部。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import streamlit as st

import config


@dataclass
class User:
    username: str
    display_name: str
    role: str  # config.ROLE_USER / config.ROLE_ADMIN


# ---------------------------------------------------------------------------
# 使用者名冊（本機 JSON；首次啟動自動建立一個預設管理藥師帳號）
# ---------------------------------------------------------------------------
def _default_users() -> dict[str, dict]:
    return {
        "admin": {"display_name": "藥劑部管理藥師", "role": config.ROLE_ADMIN, "pin": "admin"},
        "pharmacist": {"display_name": "新藥審查藥師", "role": config.ROLE_USER, "pin": "user"},
    }


def _load_users() -> dict[str, dict]:
    if not config.USERS_FILE.exists():
        users = _default_users()
        config.USERS_FILE.write_text(
            json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return users
    return json.loads(config.USERS_FILE.read_text(encoding="utf-8"))


def _save_users(users: dict[str, dict]) -> None:
    config.USERS_FILE.write_text(
        json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_users() -> dict[str, dict]:
    return _load_users()


def upsert_user(username: str, display_name: str, role: str, pin: str) -> None:
    users = _load_users()
    users[username] = {"display_name": display_name, "role": role, "pin": pin}
    _save_users(users)


def delete_user(username: str) -> None:
    users = _load_users()
    users.pop(username, None)
    _save_users(users)


# ---------------------------------------------------------------------------
# 登入狀態（存在 st.session_state）
# ---------------------------------------------------------------------------
SESSION_KEY = "auth_user"


def current_user() -> User | None:
    data = st.session_state.get(SESSION_KEY)
    return User(**data) if data else None


def login(username: str, pin: str) -> bool:
    users = _load_users()
    record = users.get(username)
    if not record or record.get("pin") != pin:
        return False
    st.session_state[SESSION_KEY] = {
        "username": username,
        "display_name": record["display_name"],
        "role": record["role"],
    }
    return True


def logout() -> None:
    st.session_state.pop(SESSION_KEY, None)


def is_admin() -> bool:
    user = current_user()
    return bool(user and user.role == config.ROLE_ADMIN)


def require_login_ui() -> User | None:
    """
    在 sidebar 顯示登入/登出區塊。已登入回傳 User；未登入回傳 None
    （呼叫端 app.py 應該在 None 時擋掉主要功能、只顯示登入畫面）。
    """
    user = current_user()
    with st.sidebar:
        st.markdown("### 🔐 使用者登入")
        if user:
            st.success(f"目前登入：**{user.display_name}**\n\n角色：{user.role}")
            if st.button("登出", use_container_width=True):
                logout()
                st.rerun()
        else:
            with st.form("login_form", clear_on_submit=False):
                u = st.text_input("帳號")
                p = st.text_input("密碼 / PIN", type="password")
                submitted = st.form_submit_button("登入", use_container_width=True)
            if submitted:
                if login(u, p):
                    st.rerun()
                else:
                    st.error("帳號或密碼錯誤")
    return current_user()
