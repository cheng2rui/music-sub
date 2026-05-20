const BASE = '/animal-island'

export const animalAsset = (name) => `${BASE}/${name}`
export const nookAsset = (name) => animalAsset(`nook-phone/${name}`)

export const animalIslandIcons = Object.freeze({
  app: nookAsset('AppIcons.svg'),
  camera: nookAsset('Property-Camera.svg'),
  chat: nookAsset('Property-Chat.svg'),
  close: animalAsset('animal_icon.svg'),
  helicopter: nookAsset('Property-Helicopter.svg'),
  home: nookAsset('nook1.svg'),
  nook: nookAsset('nook2.svg'),
  recipes: nookAsset('Property-Recipes.svg'),
  shopping: nookAsset('Property-Shopping.svg'),
  system: animalAsset('animal_icon.svg'),
})

export const requiredAnimalIslandAssets = Object.freeze([
  animalAsset('animal_icon.svg'),
  animalAsset('content_bg_pc.jpg'),
  animalAsset('guide-bg-line.webp'),
  animalAsset('home_bg.svg'),
  animalAsset('menu_bg.svg'),
  animalAsset('components/cursor-icon.png'),
  animalAsset('components/divider_line.png'),
  ...Object.values(animalIslandIcons),
])
