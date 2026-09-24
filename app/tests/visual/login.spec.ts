import { test, expect, type Page } from '@playwright/test';

async function bridge(page: Page, scenario = 'success') {
  await page.clock.install({time:new Date('2026-09-17T22:42:20Z')});
  await page.clock.pauseAt(new Date('2026-09-17T22:42:21Z'));
  await page.addInitScript(({scenario}) => {
    const account = {login:81740106, server:'ExnessKE-MT5Trial10', name:'Haddan',tradeMode:'DEMO',currency:'USD',readOnly: scenario !== 'master'};
    const ids = ['terminal','account','account_type','symbol','instrument','clock','clock_proof','history','spread'];
    const report = {account, symbol:{broker:'XAUUSDm',canonical:'XAUUSD',digits:2,point:.01,contractSize:100,spreadPoints:14},
      clock:{offsetS:0,source:'measured',proven:false,proofDetail:'Unproven ? TWELVE_DATA_API_KEY is not configured.',clockVersion:1},
      history:{M1:{bars:100,required:129600,ok:false},M5:{bars:100,required:51840,ok:false}},
      checks: ids.map(id => ({id,state:id === 'clock_proof' || id === 'history' ? 'warn' : 'pass',message:id === 'clock_proof' ? 'Unproven ? TWELVE_DATA_API_KEY is not configured.' : id === 'history' ? 'History short ? download history.' : `${id} verified`})),symbols:['XAUUSDm']};
    const data: any = window;
    data.__connectCount = 0; data.__passwordSubmitted = false;
    data.oracle = {
      mode: async () => scenario.startsWith('studio') ? 'studio' : 'login',
      settings: async () => ({profiles:scenario === 'profiles' ? [{...account,passwordType:'master',lastUsedMs:Date.now()-7200000}] : [],
        servers:['ExnessKE-MT5Trial10','ExnessKE-MT5Real10'],lastServer:'ExnessKE-MT5Trial10',terminalPath:'C:/Program Files/MetaTrader 5 EXNESS/terminal64.exe',idleLockMin:null,signupUrl:'https://my.exness.com/accounts/sign-up/',downloadUrl:'https://www.exness.com/metatrader-5/'}),
      connect: async (request: any) => {
        data.__connectCount++; data.__passwordSubmitted = !!request.password;
        data.__requestRef = request;
        if (scenario === 'auth-failed') return {error:{code:'AUTH_FAILED',message:'Login or password rejected by ExnessKE-MT5Trial10.',field:'password',actions:['forgot-password']}};
        if (scenario === 'wrong-server') return {error:{code:'WRONG_SERVER',message:"That login isn't on ExnessKE-MT5Trial10.",field:'server',actions:['choose-server']}};
        if (scenario === 'terminal-missing') return {error:{code:'TERMINAL_NOT_FOUND',message:"MetaTrader 5 isn't installed, or ORACLE can't find it.",field:'terminalPath',actions:['pick-path','download']}};
        return {report};
      },
      connectProfile: async () => ({report}),
      preflight: async () => ({report}),
      enterStudio: async () => {data.__entered=true;},
      session: async () => ({tradeMode:scenario === 'studio-real' ? 'REAL' : 'DEMO',clockProven:false,tradingCapable:scenario === 'studio-master',state:'connected',
        // Deliberately malicious extra data: the rendered broadcast must ignore it.
        balance:'$91,234.56',equity:'$99,999.99',freeMargin:'?88,888.88',profit:'-$7,777.77'}),
      switchAccount: async () => {data.__sessionCallback?.({tradeMode:'DEMO',clockProven:false,tradingCapable:false,state:'reconnecting'});},
      copyDiagnostics: async () => {}, pickTerminal: async () => 'C:/MT5/terminal64.exe',openExternal:async (kind: string)=>{data.__external=kind;},openTerminal:async()=>{},
      onProgress: (_callback: any) => () => {},
      onSession: (callback: any) => {data.__sessionCallback=callback; return ()=>{};},
    };
  }, {scenario});
  await page.goto('/');
}
async function fill(page: Page) {
  await page.getByLabel('Account login', {exact:true}).fill('81740106');
  await page.getByLabel('Password', {exact:true}).fill('fixture-only-never-a-real-password');
  await expect(page.getByRole('button', {name:'Connect to terminal'})).toBeEnabled();
}

test('login defaults investor and clears transient password after one send', async ({page}) => {
  await bridge(page, 'auth-failed');
  await expect(page.getByRole('button', {name:/Investor/})).toHaveAttribute('aria-pressed','true');
  await fill(page); await page.getByRole('button', {name:'Connect to terminal'}).click();
  await expect(page.getByRole('alert')).toContainText('Login or password rejected');
  await expect(page.getByLabel('Password', {exact:true})).toBeFocused();
  await expect(page.getByLabel('Password', {exact:true})).toHaveValue('');
  expect(await page.evaluate(()=>[(window as any).__connectCount,(window as any).__passwordSubmitted,(window as any).__requestRef.password])).toEqual([1,true,'']);
});
test('wrong server highlights dropdown', async ({page}) => {
  await bridge(page,'wrong-server'); await fill(page); await page.getByRole('button',{name:'Connect to terminal'}).click();
  await expect(page.getByRole('combobox')).toBeFocused(); await expect(page.getByRole('combobox')).toHaveAttribute('aria-invalid','true');
});
test('terminal failure is actionable and never a password failure', async ({page}) => {
  await bridge(page,'terminal-missing'); await fill(page); await page.getByRole('button',{name:'Connect to terminal'}).click();
  await expect(page.getByRole('alert')).toContainText("MetaTrader 5 isn't installed");
  await expect(page.getByRole('alert')).not.toContainText('password');
  await expect(page.getByRole('button',{name:'Download MT5',exact:true})).toBeVisible();
});
test('unproven preflight enables Studio; DEMO and no money shown', async ({page}) => {
  await bridge(page); await fill(page); await page.getByRole('button',{name:'Connect to terminal'}).click();
  await expect(page.getByTestId('account-mode')).toHaveText('DEMO');
  await expect(page.getByRole('button',{name:'Enter Studio'})).toBeEnabled();
  await expect(page.locator('.check-row.warn').filter({hasText:'Clock proof'})).toContainText('Unproven');
  await expect(page.locator('.master-banner')).toHaveCount(0);
  await page.getByRole('button',{name:'Enter Studio'}).click(); expect(await page.evaluate(()=>(window as any).__entered)).toBe(true);
});
test('master mode warning remains explicit', async ({page}) => {
  await bridge(page,'master'); await page.getByRole('button',{name:'Master',exact:true}).click();
  await expect(page.locator('.inline-warning')).toContainText('ORACLE never trades.');
  await fill(page); await page.getByRole('button',{name:'Connect to terminal'}).click();
  await expect(page.locator('.master-banner')).toContainText('Trading-capable session. ORACLE still never trades.');
});
test('saved profile screen and new profile resets Investor', async ({page}) => {
  await bridge(page,'profiles'); await expect(page.locator('.profile-row')).toContainText('81740106');
  await expect(page.getByLabel('Password',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Use a different account'}).click();
  await expect(page.getByRole('button',{name:/Investor/})).toHaveAttribute('aria-pressed','true');
});
test('paste strips spaces and free-text server remains available', async ({page}) => {
  await bridge(page);
  await page.getByLabel('Account login',{exact:true}).evaluate(element=>{const data=new DataTransfer();data.setData('text','81 740 106');element.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,clipboardData:data}));});
  await expect(page.getByLabel('Account login',{exact:true})).toHaveValue('81740106');
  await page.getByRole('combobox').fill('ExnessNEW-MT5Trial999'); await page.getByLabel('Password',{exact:true}).fill('fixture-only');
  await expect(page.getByRole('button',{name:'Connect to terminal'})).toBeEnabled();
});
test('signup invokes external-browser action', async ({page})=>{
  await bridge(page);await page.getByRole('button',{name:'Create a free account on Exness'}).click();
  expect(await page.evaluate(()=>(window as any).__external)).toBe('signup');
});
test('login visual',async({page})=>{await bridge(page);await expect(page.locator('.gate-card')).toBeVisible();await expect(page).toHaveScreenshot('login.png');});
test('preflight visual',async({page})=>{await bridge(page);await fill(page);await page.getByRole('button',{name:'Connect to terminal'}).click();await expect(page.getByRole('button',{name:'Enter Studio'})).toBeVisible();await expect(page).toHaveScreenshot('preflight.png',{fullPage:true});});
test('DEMO badge cannot be removed and money is absent in both broadcast themes', async ({page}) => {
  await bridge(page,'studio-demo');
  await expect(page.getByTestId('account-mode')).toBeVisible();
  await page.keyboard.press('F9');
  for (const theme of ['dark','light']) {
    await expect(page.getByTestId('account-mode')).toBeVisible(); await expect(page.getByTestId('account-mode')).toHaveText('DEMO');
    await expect(page.getByTestId('clock-status')).toHaveText('Clock unproven');
    const rendered = await page.getByTestId('studio').innerText();
    expect(rendered).not.toMatch(/91,234|99,999|88,888|7,777|balance|equity|free margin|P\/L/i);
    await expect(page.getByTestId('studio')).toHaveScreenshot(`studio-demo-${theme}.png`);
    if (theme === 'dark') await page.getByRole('button',{name:'Toggle theme'}).click();
  }
  expect(await page.getByRole('button',{name:/hide.*badge/i}).count()).toBe(0);
  await page.getByRole('button',{name:'Switch account'}).click();
  await expect(page.getByRole('status')).toHaveText('Reconnecting');
});
test('REAL badge and master banner persist in studio chrome', async({page})=>{
  await bridge(page,'studio-real');await expect(page.getByTestId('account-mode')).toHaveText('REAL');
  await page.reload(); await expect(page.getByTestId('account-mode')).toHaveText('REAL');
});
