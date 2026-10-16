// Synthetic two-channel CSV source, not an analog acquisition/protection circuit.
// App: 115200 baud, Auto/CSV, comma delimiter, 200 samples/s.
// Expected tones: 5 Hz and 17 Hz. Uses ordinary Arduino Serial and math APIs.

const unsigned long samplePeriodUs = 5000; // 200 samples/s
unsigned long nextSampleUs;
unsigned long sampleIndex = 0;

void setup() {
  Serial.begin(115200);
  nextSampleUs = micros();
}

void loop() {
  const unsigned long now = micros();
  if ((long)(now - nextSampleUs) < 0) {
    return;
  }
  nextSampleUs += samplePeriodUs;
  const double t = sampleIndex++ / 200.0;
  Serial.print(sin(2.0 * PI * 5.0 * t), 5);
  Serial.print(',');
  Serial.println(0.5 * sin(2.0 * PI * 17.0 * t), 5);
}
