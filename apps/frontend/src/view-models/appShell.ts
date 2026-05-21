import {
  PRIMARY_NAV_ITEMS,
  SECTION_NAV_ITEMS,
  resolvePrimaryNavKey,
  type PrimaryNavItem,
  type SectionNavItem,
} from "../app/navigation";

export type AppShellViewModel = {
  activePrimary: PrimaryNavItem;
  sectionNavItems: SectionNavItem[];
};

export function buildAppShellViewModel(pathname: string): AppShellViewModel {
  const activePrimaryKey = resolvePrimaryNavKey(pathname);
  const activePrimary =
    PRIMARY_NAV_ITEMS.find((item) => item.key === activePrimaryKey) ?? PRIMARY_NAV_ITEMS[0];

  return {
    activePrimary,
    sectionNavItems: SECTION_NAV_ITEMS[activePrimaryKey] ?? [],
  };
}
