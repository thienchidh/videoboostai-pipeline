/**
 * Returns a random integer in [min, max] (inclusive)
 */
export function randInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min
}

/**
 * Returns a random delay in [min, max] ms
 */
export function randDelay(min, max) {
  return randInt(min, max)
}

/**
 * Pick a random element from an array
 */
export function randPick(arr) {
  return arr[Math.floor(Math.random() * arr.length)]
}
