// CSV: device_time_us, sequence, signal_A, signal_B.
// App: 115200 baud, Auto/CSV, comma, timestamp column 1 (Microseconds),
// sequence column 2, configured sample rate 200 samples/s.
// Synthetic signals only, not an analog acquisition or protection circuit.
// micros() rollover is intentionally not hidden: the app reports a clock reset.

const unsigned long periodUs = 5000;
unsigned long nextSampleUs;
unsigned long sequenceNumber = 0;

void setup() {
  Serial.begin(115200);
  nextSampleUs = micros();
}

void loop() {
  const unsigned long sampleTimeUs = micros();
  if ((long)(sampleTimeUs - nextSampleUs) < 0) {
    return;
  }
  nextSampleUs += periodUs;
  const double t = sampleTimeUs / 1000000.0;
  Serial.print(sampleTimeUs);
  Serial.print(',');
  Serial.print(sequenceNumber++);
  Serial.print(',');
  Serial.print(sin(2.0 * PI * 5.0 * t), 5);
  Serial.print(',');
  Serial.println(0.5 * sin(2.0 * PI * 17.0 * t), 5);
}
