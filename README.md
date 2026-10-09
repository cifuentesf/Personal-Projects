# Personal-Projects

Repositorio base para construir una app móvil enfocada en combatir la procrastinación, con foco especial en el uso impulsivo de **Instagram** y **YouTube**.

## Objetivo del proyecto

Crear una experiencia que ayude a:
- detectar impulsos de abrir redes sociales,
- introducir fricción antes de entrar a apps distractoras,
- convertir ese impulso en bloques cortos de enfoque.

## Plataforma

- ✅ **iOS primero** (diseño pensado para iPhone 13).
- ✅ **Android compatible** desde la misma base de código.
- Stack: **React Native + Expo + TypeScript**.

## Estructura

- `/mobile`: app principal cross-platform.

## Ejecutar el proyecto

```bash
cd /home/runner/work/Personal-Projects/Personal-Projects/mobile
npm install
npm run ios
```

También puedes usar:

```bash
npm run android
npm run start
```

## MVP inicial implementado

La pantalla inicial incluye:
- mensaje de enfoque anti-procrastinación,
- lista de apps distractoras clave (Instagram y YouTube),
- acciones rápidas para redirigir el impulso (respirar, bloque de enfoque, escribir objetivo).
