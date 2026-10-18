# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026-present ROCKNIX (https://github.com/ROCKNIX)

PKG_NAME="nds-icons"
PKG_VERSION="1.0"
PKG_LICENSE="GPLv2"
PKG_SITE=""
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain Python3 p7zip"
PKG_LONGDESC="Adds Nintendo DS banner icons and titles to the EmulationStation gamelist."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/bin
    cp -a ${PKG_DIR}/sources/nds-icons ${INSTALL}/usr/bin
    chmod 0755 ${INSTALL}/usr/bin/nds-icons

  mkdir -p ${INSTALL}/usr/lib/autostart/common
    cp -a ${PKG_DIR}/autostart/120-nds-icons ${INSTALL}/usr/lib/autostart/common
    chmod 0755 ${INSTALL}/usr/lib/autostart/common/120-nds-icons
}
