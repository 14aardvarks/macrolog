// Text of the "How to use Macrolog" guide in Settings. Plain data: edit the words here.
// Keep each bullet short, plain and free of dashes.
export const GUIDE_TITLE = 'How to use Macrolog';

export const GUIDE = [
  { heading: 'Logging a food', bullets: [
    'Tap Add, then pick from Favorites, Yesterday or Recipes.',
    'Or search, scan a barcode, or type the digits under the barcode.',
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
  { heading: 'Recipes', bullets: [
    'On Today, tap Save today as a recipe.',
    'Log it later from Add, then Recipes.',
    'You can change the amounts before you log.',
  ] },
  { heading: 'Today', bullets: [
    'The chart splits your calories, with your goal in the middle.',
    'Bars show eaten, goal, percent and what is left.',
    'Tap an entry to change it.',
    'Tap X to remove it.',
  ] },
  { heading: 'Not found?', bullets: [
    'Ask Claude to read a photo of the nutrition label, if it is set up.',
    'Or choose Enter manually.',
    'Always check the numbers before saving.',
  ] },
  { heading: 'Claude', bullets: [
    'Claude is optional. Macrolog works fully without it.',
    'It always asks first, showing the request count and estimated cost.',
    'Requests are capped each month for the whole household.',
    'You can turn the question off in Settings.',
  ] },
  { heading: 'Two users', bullets: [
    'Each person has their own log, goals and settings.',
    'Foods are shared.',
  ] },
];
