import js from '@eslint/js';
import globals from 'globals';

export default [
  js.configs.recommended,
  {
    linterOptions: {reportUnusedDisableDirectives: 'error'},
    rules: {
      eqeqeq: 'error',
      'no-var': 'error',
      'prefer-const': 'error',
      'no-implicit-coercion': 'error',
    },
  },
  {
    files: ['extension/*.js'],
    languageOptions: {globals: {...globals.browser, chrome: 'readonly'}},
    rules: {'no-magic-numbers': ['error', {ignore: [0, 1], ignoreArrayIndexes: true, enforceConst: true}]},
  },
  {
    files: ['tests/*.mjs', 'eslint.config.js'],
    languageOptions: {globals: {...globals.node, ...globals.browser, chrome: 'readonly'}},
  },
];
