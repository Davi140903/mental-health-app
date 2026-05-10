const LIA_CHECKIN_COOLDOWN_PREFIX = 'mental-health-lia-checkin-cooldown';
const LIA_LIGHT_PROMPT_PREFIX = 'mental-health-lia-light-prompt';

const CHECKIN_COOLDOWN_MINUTES = 5;

export function getCheckInCooldownStorageKey(userId: string) {
  return `${LIA_CHECKIN_COOLDOWN_PREFIX}:${userId}`;
}

export function getLightPromptStorageKey(userId: string) {
  return `${LIA_LIGHT_PROMPT_PREFIX}:${userId}`;
}

export function getCheckInCooldownExpiresAt() {
  const expiresAt = new Date();
  expiresAt.setMinutes(expiresAt.getMinutes() + CHECKIN_COOLDOWN_MINUTES);
  return expiresAt.toISOString();
}

export function hasActiveCheckInCooldown(userId: string) {
  const rawValue = localStorage.getItem(getCheckInCooldownStorageKey(userId));
  if (!rawValue) {
    return false;
  }

  const expiresAt = new Date(rawValue);
  if (Number.isNaN(expiresAt.getTime())) {
    localStorage.removeItem(getCheckInCooldownStorageKey(userId));
    return false;
  }

  if (expiresAt.getTime() <= Date.now()) {
    localStorage.removeItem(getCheckInCooldownStorageKey(userId));
    return false;
  }

  return true;
}
