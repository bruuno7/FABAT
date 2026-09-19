/* Una pestaña duplicada puede heredar sessionStorage: nunca hereda la conversación. */
window.mandoChatTab = async function (store, key) {
  const fresh = () => crypto.getRandomValues(new Uint32Array(4)).join('-');
  const reset = () => { store.tabKey = fresh(); store.convs = []; store.cur = null; store.strikes = []; store.session = null; };
  if (!store.tabKey) store.tabKey = fresh();
  if (navigator.locks) {
    const claim = name => new Promise(resolve => {
      navigator.locks.request('mando-chat-tab:' + name, {ifAvailable:true}, lock => {
        resolve(!!lock);
        // El navegador libera este cerrojo al cerrar o recargar el documento.
        if (lock) return new Promise(() => {});
      }).catch(() => resolve(false));
    });
    if (!await claim(store.tabKey)) { reset(); await claim(store.tabKey); }
  } else if (performance.getEntriesByType('navigation')[0]?.type !== 'reload') {
    // HTTP LAN sin Web Locks: una navegación nueva empieza sin avisos heredados.
    reset();
  }
  try { sessionStorage.setItem(key, JSON.stringify(store)); } catch (_) { /* almacenamiento privado */ }
};
