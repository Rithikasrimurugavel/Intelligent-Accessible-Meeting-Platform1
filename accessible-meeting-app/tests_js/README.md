# Browser-component tests (optional)

These run the real JavaScript of the two custom components inside a simulated browser (jsdom) with a fake
microphone / speaker / camera, so the logic can be checked without opening Chrome.

```bash
cd tests_js
npm install jsdom@24
node voice_component.test.js
node sign_component.test.js
```
Every line should print `PASS`.
