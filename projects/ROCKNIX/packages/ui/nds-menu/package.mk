# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026-present ROCKNIX (https://github.com/ROCKNIX)

PKG_NAME="nds-menu"
PKG_VERSION="1.0"
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE=""
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain Python3 SDL2 SDL2_image SDL2_ttf"
PKG_LONGDESC="DS-style two-screen launcher for the Anbernic RG DS."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/share/nds-menu
    cp -a ${PKG_DIR}/sources/main.py ${PKG_DIR}/sources/sdl2.py ${PKG_DIR}/sources/fonts ${INSTALL}/usr/share/nds-menu

  mkdir -p ${INSTALL}/usr/bin
    cp -a ${PKG_DIR}/sources/nds-menu ${INSTALL}/usr/bin
    chmod 0755 ${INSTALL}/usr/bin/nds-menu
}
