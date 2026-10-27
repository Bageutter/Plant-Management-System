(() => {
  const button = document.getElementById('henny-hop');
  if (!button) return;
  const hello = button.closest('.henny-hello');
  let audio, timer;
  function cluck() {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return;
    audio ||= new Audio();
    audio.resume().catch(() => {});
    // Short, soft two-part cluck, synthesised locally after a deliberate click.
    for (let i=0;i<2;i++) {
      const t=audio.currentTime+i*.13;
      const oscillator=audio.createOscillator(), gain=audio.createGain();
      oscillator.type='triangle';oscillator.frequency.setValueAtTime(620-i*100,t);
      oscillator.frequency.exponentialRampToValueAtTime(170,t+.08);
      gain.gain.setValueAtTime(0,t);gain.gain.linearRampToValueAtTime(.13,t+.008);
      gain.gain.exponentialRampToValueAtTime(.001,t+.09);
      oscillator.connect(gain);gain.connect(audio.destination);
      oscillator.start(t);oscillator.stop(t+.1);
    }
  }
  button.addEventListener('click', () => {
    clearTimeout(timer);hello.classList.remove('is-hopping');
    requestAnimationFrame(() => requestAnimationFrame(() => hello.classList.add('is-hopping')));
    cluck();timer=setTimeout(() => hello.classList.remove('is-hopping'),850);
  });
})();
