// Text of the "How to use Macrolog" guide in Settings. Plain data: edit the words here.
// Keep each bullet short, plain and free of dashes.
export const GUIDE_TITLE = 'How to use Macrolog';

export const GUIDE = [
  { heading: 'Logging a food', bullets: [
    'Tap Add, then pick from Favorites, Yesterday or Recipes.',
    'Or search, or tap Scan Barcode. The camera starts at once.',
    'No camera? On the scan screen, type the digits under the barcode.',
    'Set the amount, then tap Log.',
  ] },
  { heading: 'The Meal selector on Add', bullets: [
    'It filters the lists by meal.',
    'All shows everything.',
  ] },
  { heading: 'The picker', bullets: [
    'Two wheels: amount on the left, unit on the right.',
    'Scroll, use the arrow keys, or tap a row to pick it.',
    'Tap the chosen amount, or Type, to enter it. Try 1/2 or 1,5.',
    'Servings count in quarters, like 1/4 or 1 1/2, or 0.25 and 1.5.',
    'Choose fractions or decimals in Settings.',
    '% of serving is for partial servings.',
    'Macros update live and always convert back to the label\'s grams and calories.',
  ] },
  { heading: 'How it remembers', bullets: [
    'A food reopens with the amount and unit from your last entry.',
    'The first time, it uses the label\'s serving.',
    'Turn this off with Start from my last entry.',
    'Favorites and Yesterday show last used amounts.',
  ] },
  { heading: 'Favorites', bullets: [
    'Tap the star on a food to add or remove it.',
  ] },
  { heading: 'Saved and meal tags', bullets: [
    'Settings, then Saved, lets you tag, rename, edit and delete.',
    'Untagged items show under every meal. Logging with a meal adds its tag.',
  ] },
  { heading: 'Recipes', bullets: [
    'On Today, tap Save as recipe under a meal.',
    'Log it later from Add, then Recipes.',
    'Untick items to skip them, and change amounts.',
    'Tap an item\'s name to adjust it in the picker, with any unit, then tap Done.',
  ] },
  { heading: 'Today', bullets: [
    'The chart splits your calories, with your goal in the middle.',
    'Bars show eaten, goal, percent and what is left.',
    'A thin bar under each food shows its carbs, protein and fat share.',
    'Tap an entry to change it.',
    'Tap X to remove it.',
  ] },
  { heading: 'Not found?', bullets: [
    'Ask Claude to read a photo of the nutrition label, if it is set up.',
    'Or choose Enter Manually.',
    'Always check the numbers before saving.',
  ] },
  { heading: 'Claude', bullets: [
    'Claude is optional. Macrolog works fully without it.',
    'It always asks first, showing the request count and estimated cost.',
    'Requests are capped each month for the whole household.',
    'You can turn the question off in Settings.',
  ] },
  { heading: 'Your Claude key', bullets: [
    'In Settings you can add your own Claude key and monthly limit.',
    'It bills your Anthropic account and is used instead of the shared key.',
    'The key is never shown again after you save it.',
  ] },
  { heading: 'Single sign-on (SSO)', bullets: [
    'If your server offers it, tap Connect SSO in Settings.',
    'Then you can sign in with the provider button.',
    'Disconnect needs a password on your account.',
  ] },
  { heading: 'Admin', bullets: [
    'Only administrators see Admin in Settings.',
    'Add users, reset passwords, and turn the shared Claude key on or off per person.',
    'Sign-in has the SSO setup, the redirect URI to copy and Test connection.',
    'Claude and USDA keys are saved here and never shown again.',
    'Use default puts a setting back to its environment value.',
    'Activity lists the latest admin changes.',
  ] },
  { heading: 'Two users', bullets: [
    'Each person has their own log, goals and settings.',
    'Foods are shared.',
  ] },
];
