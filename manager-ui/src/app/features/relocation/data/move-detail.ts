import type {
  CreatedApplication,
  MoveCurrent,
  MoveDetail,
  MoveFact,
  MoveInventory,
  MovePhase,
} from './relocation.types';

function records(value: unknown): readonly Readonly<Record<string, unknown>>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null) : [];
}

function inventoryOf(value: unknown): MoveInventory | null {
  if (typeof value !== 'object' || value === null) {
    return null;
  }
  const found = value as Record<string, unknown>;
  return Array.isArray(found['applications']) ? (found as unknown as MoveInventory) : null;
}

function isPhase(value: Readonly<Record<string, unknown>>): boolean {
  return typeof value['phase'] === 'string' && typeof value['status'] === 'string' && Array.isArray(value['steps']);
}

function isFact(value: Readonly<Record<string, unknown>>): boolean {
  return typeof value['code'] === 'string';
}

function isCreated(value: Readonly<Record<string, unknown>>): boolean {
  return typeof value['target'] === 'string' && typeof value['name'] === 'string';
}

function currentOf(value: unknown): MoveCurrent | null {
  if (typeof value !== 'object' || value === null) {
    return null;
  }
  const found = value as Record<string, unknown>;
  return typeof found['step'] === 'string' ? (found as unknown as MoveCurrent) : null;
}

export function moveDetailOf(detail: Readonly<Record<string, unknown>>): MoveDetail {
  const leftovers = detail['leftovers'];
  return {
    rehearsal: detail['rehearsal'] === true,
    inventory: inventoryOf(detail['inventory']),
    phases: records(detail['phases']).filter(isPhase) as unknown as readonly MovePhase[],
    blockers: records(detail['blockers']).filter(isFact) as unknown as readonly MoveFact[],
    leftovers: Array.isArray(leftovers) ? leftovers.filter((item): item is string => typeof item === 'string') : [],
    created: records(detail['created_applications']).filter(isCreated) as unknown as readonly CreatedApplication[],
    current: currentOf(detail['current']),
  };
}
