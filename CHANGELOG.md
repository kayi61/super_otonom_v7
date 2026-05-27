# CHANGELOG — super_otonom

## [7.1.1](https://github.com/kayi61/super_otonom_v7/compare/super_otonom-v7.1.0...super_otonom-v7.1.1) (2026-05-27)


### Bug Fixes

* **ci:** handle missing nightly kupiec input files ([8f3b471](https://github.com/kayi61/super_otonom_v7/commit/8f3b4711b54c587895d84218f8f1ba6e6b810ab9))
* **ci:** skip nightly kupiec when backtest input files missing ([6a10b5c](https://github.com/kayi61/super_otonom_v7/commit/6a10b5cf61215e9547a09147849d16f3245a737d))

## [7.1.0](https://github.com/kayi61/super_otonom_v7/compare/super_otonom-v7.0.0...super_otonom-v7.1.0) (2026-05-26)


### Features

* 10-day VaR/CVaR Basel FRTB sqrt(10) scaling ([e0e57e4](https://github.com/kayi61/super_otonom_v7/commit/e0e57e4e886f502b9077cd2e520c76cafad307c0))
* add HA / multi-instance support with Redis leader election (Prompt 13) ([60196f7](https://github.com/kayi61/super_otonom_v7/commit/60196f77ae398f35c3cbccd8380b4046466baa80))
* add TWAP/VWAP algo execution engine (Prompt 12) ([43f291e](https://github.com/kayi61/super_otonom_v7/commit/43f291e792d03472db95ae492e6a580eebf08743))
* audit 4 institutional survivorship — schedule validation and PIT universe ([12d3ad6](https://github.com/kayi61/super_otonom_v7/commit/12d3ad641e4955e4d7fac5e3ace2b3ac8f46b0cf))
* audit 4 institutional survivorship (phase 2) ([ffc9030](https://github.com/kayi61/super_otonom_v7/commit/ffc90305c3a193d2a0c84c0f9b4092d64710ea63))
* **audit-10:** TWAP/VWAP yurutme topolojisi ve disclosure ([9677eee](https://github.com/kayi61/super_otonom_v7/commit/9677eee525d727a397d0d0321df365c6522fc856))
* **audit-11:** VaR/CVaR topolojisi ve kurumsal iddia disclosure ([87c0321](https://github.com/kayi61/super_otonom_v7/commit/87c0321746f2d030cfe2f5cea4b7f46e52ee1f1d))
* **ci:** expand mutation testing to risk/ package — 4 critical modules ([269c625](https://github.com/kayi61/super_otonom_v7/commit/269c6253a71049f9af2c8cbb986724fd3d9df2b9))
* **ci:** expand mutation testing to risk/ package — 4 critical modules ([dcf8c8b](https://github.com/kayi61/super_otonom_v7/commit/dcf8c8b06ad4ef8c42f12eaa9265fe0df02d8b9a))
* **ci:** expand mutation testing to risk/ package — 4 critical modules ([34b939b](https://github.com/kayi61/super_otonom_v7/commit/34b939b51e4d8d9106dc40da176658fe88211d7a))
* **ci:** expand mutation testing to risk/ package — 4 modules ([6954696](https://github.com/kayi61/super_otonom_v7/commit/6954696ec76e7bc8fcd16c9d28f6606954a2328a))
* **ci:** go-build job and Faz 3-5 ops stack ([2722935](https://github.com/kayi61/super_otonom_v7/commit/2722935fe5fec6e9d6d9c314e4401e879f7aaeb9))
* **ci:** Windows release_gate workflow + aiohttp env hints (Faz 2) ([235834c](https://github.com/kayi61/super_otonom_v7/commit/235834c97fe2ab3fd5edb39889abf32eb9a93853))
* Faz B — BotEngine ↔ Risk Engine tam entegrasyon ([2d92bc0](https://github.com/kayi61/super_otonom_v7/commit/2d92bc019f6f2400798a841e6d8aab9b100179e5))
* Faz B — BotEngine ↔ Risk Engine tam entegrasyon ([d6d1c8a](https://github.com/kayi61/super_otonom_v7/commit/d6d1c8aa0f0b6285a6d991c4cb9ca59ab8a0f2bb))
* Faz C — 10-day VaR + CI workflows + model governance ([68e525a](https://github.com/kayi61/super_otonom_v7/commit/68e525a052d4428361b5ea2d87c28573ea3e9fce))
* **grafana:** VR-23 Grafana Risk Dashboard — VaR/CVaR/Basel ([ede99d1](https://github.com/kayi61/super_otonom_v7/commit/ede99d1ef1bbab547a934bda12351161c053b561))
* **grafana:** VR-23 Grafana Risk Dashboard — VaR/CVaR/Basel ([63212ce](https://github.com/kayi61/super_otonom_v7/commit/63212ce6ed5478249a9a2ed6c6557331d6ab5291))
* HA / multi-instance support with Redis leader election (Prompt 13) ([e1a3167](https://github.com/kayi61/super_otonom_v7/commit/e1a3167b1737391cf68e37cf79df90bda41d465f))
* **metrics:** VR-21 Prometheus VaR/CVaR/Stres Metrikleri — Tam Suite ([7465f45](https://github.com/kayi61/super_otonom_v7/commit/7465f450fa44a5d3d051c1ef2a7ab877ec22b086))
* **metrics:** VR-21 Prometheus VaR/CVaR/Stres Metrikleri — Tam Suite ([baff3d6](https://github.com/kayi61/super_otonom_v7/commit/baff3d6b8d6547666111343f67225a24a9304a8e))
* move 23 modules to infra/ and signals/ sub-packages (Prompt 14) ([757b191](https://github.com/kayi61/super_otonom_v7/commit/757b191c15ae1f723f0c076575802d19ff8362a3))
* observability stack and dependency security gate ([8af5b0a](https://github.com/kayi61/super_otonom_v7/commit/8af5b0adb1317f9216480971eabf51c9cd223cd3))
* package refactor — move 23 modules to infra/ and signals/ (Prompt 14) ([1f70e1d](https://github.com/kayi61/super_otonom_v7/commit/1f70e1dc1b80cd5c3669b6430ede885cde77aa89))
* **PROMPT-03:** automated backup/restore + DR runbook ([3952a56](https://github.com/kayi61/super_otonom_v7/commit/3952a561b780de659e0e1064d7fbccd910bc392e))
* **PROMPT-03:** Backup/DR automation (Timescale, Vault, Redis, GFS) ([fa00498](https://github.com/kayi61/super_otonom_v7/commit/fa00498f76ec139c0d3c689c3715b2cea6d1e2f5))
* **risk:** VR-02 Student-t parametric VaR + Monte Carlo bug fix ([acb2d26](https://github.com/kayi61/super_otonom_v7/commit/acb2d264176ff38550e11b52f27a330d9e1deedc))
* **risk:** VR-03 Cornish-Fisher VaR — skewness/kurtosis adjustment ([12970d6](https://github.com/kayi61/super_otonom_v7/commit/12970d6be7999803df13d854b32dd3f9e157eb6b))
* **risk:** VR-04 CVaR / Expected Shortfall — 3 methods + Basel FRTB ([16bd5d3](https://github.com/kayi61/super_otonom_v7/commit/16bd5d37410ef8bc71ba3125fa6e2745dbd96526))
* **risk:** VR-05 RiskConfig expansion — Basel III/FRTB + compat layer ([f33925f](https://github.com/kayi61/super_otonom_v7/commit/f33925f9ae102da42827926a160b070402a107df))
* **risk:** VR-05 RiskConfig expansion — Basel III/FRTB + compat layer ([e59098b](https://github.com/kayi61/super_otonom_v7/commit/e59098b517d20e3ee3adbe3643a3622398e38523))
* **risk:** VR-06 EVT Peaks Over Threshold tail estimation ([b36e72a](https://github.com/kayi61/super_otonom_v7/commit/b36e72a4fbf639618ed7724667c4b9a1495a5545))
* **risk:** VR-07 Filtered Historical Simulation (FHS) with GARCH(1,1) ([114f8bf](https://github.com/kayi61/super_otonom_v7/commit/114f8bf53c01ab7e1e8187059168c8259f3824b9))
* **risk:** VR-08 Liquidity-adjusted VaR (LVaR) — BDSS + time-to-liquidate ([a61ce75](https://github.com/kayi61/super_otonom_v7/commit/a61ce75e9bf2d4d9011cfed83c898f2f2405df9f))
* **risk:** VR-09 Component/Marginal/Incremental VaR decomposition ([62066ad](https://github.com/kayi61/super_otonom_v7/commit/62066ade211ce958a1dc9636b15e898868655903))
* **risk:** VR-09 Component/Marginal/Incremental VaR decomposition ([0c95e9f](https://github.com/kayi61/super_otonom_v7/commit/0c95e9f63d2d6f3a3f4cd52b2dd4a87cc352e36d))
* **risk:** VR-10 Regime-conditional VaR ([89300bc](https://github.com/kayi61/super_otonom_v7/commit/89300bcc94f7b4bc267db1bfff52607396893c2c))
* **risk:** VR-10 Regime-conditional VaR ([9d03f64](https://github.com/kayi61/super_otonom_v7/commit/9d03f647ce264369e606f6cf3fd2ded0ad554904))
* **risk:** VR-11 Stressed VaR — Basel 2.5 stress-period rescaling ([bc2218c](https://github.com/kayi61/super_otonom_v7/commit/bc2218c359dd7fc76342e0a07904b934ebb3174a))
* **risk:** VR-11 Stressed VaR (Basel 2.5) ([1c7ed11](https://github.com/kayi61/super_otonom_v7/commit/1c7ed11c97984f7d0473a82c38459aeb8e654cd2))
* **risk:** VR-12 Stress Scenario Library + Reverse Stress Test ([3911c55](https://github.com/kayi61/super_otonom_v7/commit/3911c5547feb03e8b5b9e90261109291e38d03f5))
* **risk:** VR-12 Stress Scenario Library + Reverse Stress Test ([20dfeab](https://github.com/kayi61/super_otonom_v7/commit/20dfeabe699077c0bf8b2f66eb7e47c0712f0cb1))
* **risk:** VR-13 Kupiec POF (Proportion of Failures) backtest ([c775f0b](https://github.com/kayi61/super_otonom_v7/commit/c775f0bad067d164c03b4d379949cf4087c8cda7))
* **risk:** VR-13 Kupiec POF (Proportion of Failures) backtest ([4066e78](https://github.com/kayi61/super_otonom_v7/commit/4066e78df23fb077c0c4c7be640d4cf3068a6856))
* **risk:** VR-14 Christoffersen Independence + CC Test ([c547a47](https://github.com/kayi61/super_otonom_v7/commit/c547a47cb521112167f6eef618df67e166ee5a84))
* **risk:** VR-14 Christoffersen Independence + Conditional Coverage test ([028ab69](https://github.com/kayi61/super_otonom_v7/commit/028ab693fa095cbbbe26a1f1fdeda44b3e8be6c3))
* **risk:** VR-15 Basel Traffic Light backtest ([4cee07e](https://github.com/kayi61/super_otonom_v7/commit/4cee07e43211b7995f2aa79063d92698fd78ca24))
* **risk:** VR-15 Basel Traffic Light Backtest ([188b181](https://github.com/kayi61/super_otonom_v7/commit/188b181561a010a7c4df45c5bd4efa18f20cc28a))
* **risk:** VR-16 P&L Attribution + Unexplained PnL Drift Detection ([f6a5073](https://github.com/kayi61/super_otonom_v7/commit/f6a5073ce6cc3c6ddb9de8a9aea8d9ea39526f52))
* **risk:** VR-16 P&L Attribution + Unexplained PnL Drift Detection ([c361397](https://github.com/kayi61/super_otonom_v7/commit/c361397956e47b6d5686336f77fc9f318ce6c815))
* **risk:** VR-17 Pre-trade Marginal VaR Gate ([7dac6e4](https://github.com/kayi61/super_otonom_v7/commit/7dac6e42d4ff6443c944e6d744df64744ad8e160))
* **risk:** VR-17 Pre-trade Marginal VaR Gate ([145ba77](https://github.com/kayi61/super_otonom_v7/commit/145ba77557ed629c6167ee843f5e42d6760b9ca0))
* **risk:** VR-18 VaR-aware Position Sizing (Kelly + VaR Cap) ([2caf66e](https://github.com/kayi61/super_otonom_v7/commit/2caf66e82a6879aad77ff3934c07cd0379bcf8c4))
* **risk:** VR-18 VaR-aware Position Sizing (Kelly + VaR Cap) ([7347185](https://github.com/kayi61/super_otonom_v7/commit/7347185dfc93ab66c4e7233021a9230947636e55))
* **risk:** VR-19 Kill-switch — VaR/CVaR Breach Trigger ([faf0054](https://github.com/kayi61/super_otonom_v7/commit/faf005483159738f6815da08893cbc4dfa387c16))
* **risk:** VR-19 Kill-switch — VaR/CVaR Breach Trigger ([0caaac1](https://github.com/kayi61/super_otonom_v7/commit/0caaac100f4f081a1f8f366ce54637397cb8e61d))
* **risk:** VR-20 VaR Limit Hierarchy — Strategy/Portfolio/Firm ([1434e48](https://github.com/kayi61/super_otonom_v7/commit/1434e484c4b1146c84215200ea5752ff3c43cdfa))
* **risk:** VR-20 VaR Limit Hierarchy (Strategy/Portfolio/Firm) ([25d749a](https://github.com/kayi61/super_otonom_v7/commit/25d749a65cbf68645e056e71f473fde0622c5ca5))
* **risk:** VR-22 Günlük Risk Raporu — Otomatik Üretim ([a545b8a](https://github.com/kayi61/super_otonom_v7/commit/a545b8a1d038e98311f065a908552791850619f0))
* **risk:** VR-22 Günlük Risk Raporu — Otomatik Üretim ([5b2dded](https://github.com/kayi61/super_otonom_v7/commit/5b2dded378e59147810fca3c345416e1ce03aefb))
* TWAP/VWAP algo execution engine (Prompt 12) ([554dacc](https://github.com/kayi61/super_otonom_v7/commit/554dacc736210dd3b9adc5ea65d79125ada3beb4))
* v8 sonrasi main_loop, circuit breaker ve backtester tamamlama ([e42a5a2](https://github.com/kayi61/super_otonom_v7/commit/e42a5a2266ac68e2a7a1889e24f5a6fc9e509144))
* **vr-01:** RiskEngine 99%/97.5% VaR+CVaR suite, Basel FRTB config genisletme ([f18f46b](https://github.com/kayi61/super_otonom_v7/commit/f18f46bd2c0a2e9d14c8657b9fbc7e7e94640bd1))
* **vr-01:** unified RiskEngine tek VaR kaynagi ([a30a2e2](https://github.com/kayi61/super_otonom_v7/commit/a30a2e2bcbcf479d05c4498cc549ee17efe76fa1))
* **VR-17:** wire pre_trade_var_check into BotEngine BUY flow ([e2973c8](https://github.com/kayi61/super_otonom_v7/commit/e2973c83d073ea1e7e4a6bccce9745cd0a11a857))
* **VR-17:** wire pre_trade_var_check into BotEngine._handle_entry BUY flow ([1cf3415](https://github.com/kayi61/super_otonom_v7/commit/1cf34158269e2c80032873fc55101e09efbb90bd))
* **VR-18:** wire size_with_var_cap into BotEngine BUY flow ([5507ea9](https://github.com/kayi61/super_otonom_v7/commit/5507ea958e7c8e2e0ef92285d60de347b8ec46ae))
* **VR-18:** wire size_with_var_cap into BotEngine._handle_entry BUY flow ([52a977d](https://github.com/kayi61/super_otonom_v7/commit/52a977db0f6a9cd6ffdbf76066f9d385bdb75a5d))
* **VR-19:** wire record_var_breach Prometheus into _check_var_breach ([5dd5bec](https://github.com/kayi61/super_otonom_v7/commit/5dd5bec29acf20e3540fc358698acb4c06b8a0e1))
* **VR-19:** wire record_var_breach Prometheus into _check_var_breach ([543b073](https://github.com/kayi61/super_otonom_v7/commit/543b0736529106028b740428eafd66a69aee321f))
* **VR-20:** wire check_limits into _tick_impl for runtime VaR limit enforcement ([3d91248](https://github.com/kayi61/super_otonom_v7/commit/3d91248d0c43dd176e1d7ca1310ab9d4b2413ede))
* **VR-20:** wire check_limits into tick path for runtime VaR limit enforcement ([d6acd6d](https://github.com/kayi61/super_otonom_v7/commit/d6acd6d7df36628935e280eca1a7e9b123279c9c))
* **VR-24:** Model Inventory + Validation Governance ([c9b9455](https://github.com/kayi61/super_otonom_v7/commit/c9b94553f4a6b40937647fbe5f936e25cb20be66))
* **VR-24:** Model Inventory + Validation Governance ([674ef78](https://github.com/kayi61/super_otonom_v7/commit/674ef782ecdc05218daf130abdb084ac322ad845))
* **VR-25:** Risk Appetite Statement + Escalation Matrix ([522a85d](https://github.com/kayi61/super_otonom_v7/commit/522a85dbe3005594d315ba0a8b51919641af568b))
* **VR-25:** Risk Appetite Statement + Escalation Matrix ([aba682f](https://github.com/kayi61/super_otonom_v7/commit/aba682f2937c5343ba024027799916733ab9d9df))
* **VR-26:** Property-Based VaR/CVaR Invariants (Hypothesis) ([0560718](https://github.com/kayi61/super_otonom_v7/commit/0560718d30caedd573954161a0ea56d487f14a9f))
* **VR-26:** property-based VaR/CVaR mathematical invariants (Hypothesis) ([fc5eca3](https://github.com/kayi61/super_otonom_v7/commit/fc5eca3974045afbc7bb994951bc4b35754cedd8))
* **VR-27:** statistical regime detection engine ([9edea63](https://github.com/kayi61/super_otonom_v7/commit/9edea63a64f81fab5eacf676e6e68cd3dd58b6ee))
* **VR-27:** Statistical Regime Detection Engine ([e521fe1](https://github.com/kayi61/super_otonom_v7/commit/e521fe1a5c11b438e5d0b0228735260670cb570b))
* wire portfolio risk (Faz 24) into live tick path ([a43c11d](https://github.com/kayi61/super_otonom_v7/commit/a43c11d078472c3c46991eed4f0752ea4f98365f))
* wire portfolio risk engine (Faz 24) into live tick path ([5fce85c](https://github.com/kayi61/super_otonom_v7/commit/5fce85c3926584ab450ac3aad87804d38aee3777))


### Bug Fixes

* add execution/ to allowed subpackages in package topology audit ([291217e](https://github.com/kayi61/super_otonom_v7/commit/291217ee8ba2c3b3a3f204fcacf299d83eda594c))
* add ha/ modules to HA audit allowlist ([5cc3425](https://github.com/kayi61/super_otonom_v7/commit/5cc3425b90b1c9cd35ed1ea1d302da3d5462dbbc))
* add meta_regime_orchestrator for deploy_env_check CI ([4b82e2b](https://github.com/kayi61/super_otonom_v7/commit/4b82e2bf74aba429042431dfafb1455523d7effc))
* add missing src/phases 46-55 for kanon drift CI ([294a028](https://github.com/kayi61/super_otonom_v7/commit/294a02882814cc3ec8f162ad004f834dbee4060c))
* add pytest-asyncio to dev dependencies ([6b52ef9](https://github.com/kayi61/super_otonom_v7/commit/6b52ef9e498ab2dcc1ad954bd5a984b004479159))
* add risk_institutional_summary for print_resolved_risk ([7e83fa8](https://github.com/kayi61/super_otonom_v7/commit/7e83fa8b908e69d2b9b3c0d87bce89ffed5dade8))
* add set_metrics to _StubRisk for stub-mode compatibility ([9f438bf](https://github.com/kayi61/super_otonom_v7/commit/9f438bf394f130e6c290e85a4f083fba4b5fe500))
* add staged_exit and signal_lineage modules (bot_engine CI imports) ([f1914bf](https://github.com/kayi61/super_otonom_v7/commit/f1914bfbcf6b39bd6bc1862e1fecf2a97c6f69e6))
* add tick_timing and market_snapshot modules (CI import chain) ([2b9ed09](https://github.com/kayi61/super_otonom_v7/commit/2b9ed09b3e20d896d1dbbbbb5e63265ec1304f42))
* allowlist coverage audit tests in repo scanners ([82eed45](https://github.com/kayi61/super_otonom_v7/commit/82eed4506330807604af587151c929ba9170f442))
* apply universe schedule filter before min-bar check in edge_evidence ([f52658a](https://github.com/kayi61/super_otonom_v7/commit/f52658a766c3fa786c7152b27110d9be0876cd94))
* asyncio_mode auto for CI ([daaea65](https://github.com/kayi61/super_otonom_v7/commit/daaea6533805d7c9c563e22fb432904e2955db28))
* audit 4 polish — ruff, quiet vault on backtest, Windows pytest ([7aff7cf](https://github.com/kayi61/super_otonom_v7/commit/7aff7cf3a5075d317e071c10fb58432e92cbbbe8))
* audit 4 survivorship disclosure and universe schedule ([bb45578](https://github.com/kayi61/super_otonom_v7/commit/bb45578f2300d0e11e6dee119cb6476aed2d20f7))
* audit 4 survivorship disclosure, universe schedule, multi-symbol backtest ([9d2c686](https://github.com/kayi61/super_otonom_v7/commit/9d2c6863f336a18595cabccad167a3fee7c04029))
* audit maddeleri düzeltildi ([d98e2d5](https://github.com/kayi61/super_otonom_v7/commit/d98e2d5faae7914293d682757ec6729d11864440))
* audit maddeleri düzeltildi ([616ffb0](https://github.com/kayi61/super_otonom_v7/commit/616ffb088fb8016bfe6494ca14ffa34dbe0c2e52))
* **audit-11:** resolve var_topology_manifest.json drift ([d81bf2b](https://github.com/kayi61/super_otonom_v7/commit/d81bf2b22048a67082d020e333e8accb0c32ae77))
* **audit-11:** resolve var_topology_manifest.json drift — live_tick_var_source & RiskEngine detection ([f303386](https://github.com/kayi61/super_otonom_v7/commit/f303386b5030b977a8fdd50a219fc48651667148))
* **audit-9:** layout_topology coverage ve manifest set bug ([79abd04](https://github.com/kayi61/super_otonom_v7/commit/79abd04a4efd9e7496926b66e212b203c3a033bb))
* bot_engine_audit manifest güncelle (Faz A stub satırları) ([1341af6](https://github.com/kayi61/super_otonom_v7/commit/1341af6136ef3cb7c2efc0be817c0a065c3c3141))
* **cd:** CD tag filter + release-please repo setup ([f6e1e20](https://github.com/kayi61/super_otonom_v7/commit/f6e1e20ad278a7f1379814e1799e5a2cdaad1b6d))
* **cd:** Docker build + release-please manifest ([e057855](https://github.com/kayi61/super_otonom_v7/commit/e0578555607850e621211898e5fafe1175d2b570))
* **cd:** Dockerfile _setup_build + release-please manifest + staging deploy ([b5f67e8](https://github.com/kayi61/super_otonom_v7/commit/b5f67e86282f7c157067c8d1059cb35748e66df1))
* **cd:** valid tag filter v* + release-please permissions docs ([b51c9cf](https://github.com/kayi61/super_otonom_v7/commit/b51c9cfee6443316088f6afb09166c0905918348))
* **ci:** add CapitalEngine journal_sink for fastrun test ([7f79929](https://github.com/kayi61/super_otonom_v7/commit/7f799291d581b63c94ad977c3369c01e036b3da4))
* **ci:** add explicit token + persist-credentials to coverage checkout ([89f5faa](https://github.com/kayi61/super_otonom_v7/commit/89f5faab5975b7e1c8f0f01ec96f86fadf8293f2))
* **ci:** add missing engine_managers module for bot_engine import ([4868e22](https://github.com/kayi61/super_otonom_v7/commit/4868e22c3dc1c5bd5431473ae4f1c82a36f003d5))
* **ci:** commit fastrun 5000 phase tests for ci-quick gate ([73a0a14](https://github.com/kayi61/super_otonom_v7/commit/73a0a14c9195438a8ee513f5ef084c173ecddc18))
* **ci:** deploy_env_check on GHA, ruff sweep cleanup ([4af84a1](https://github.com/kayi61/super_otonom_v7/commit/4af84a1a28e3509139fbb8e0d8d5db01b5942845))
* **ci:** downgrade actions v6 to stable v4/v5 ([429953b](https://github.com/kayi61/super_otonom_v7/commit/429953b912c7db789e61c20f572074c152714046))
* **ci:** downgrade actions/checkout v6-&gt;v4, setup-python v6-&gt;v5 ([eb51645](https://github.com/kayi61/super_otonom_v7/commit/eb51645e36f96ad9ed77f58f525c1da119a1f2d6))
* **ci:** enable coverage parallel mode for pytest-xdist. ([004e105](https://github.com/kayi61/super_otonom_v7/commit/004e1052a538ae4e2c988811c5db1066f10a2768))
* **ci:** explicit token for coverage checkout auth ([af78c60](https://github.com/kayi61/super_otonom_v7/commit/af78c602a409bd096902f99ee8e5d489e94b784f))
* **ci:** mutation 6h timeout, string haric, hedef testler ([7f26d83](https://github.com/kayi61/super_otonom_v7/commit/7f26d83b7de96b72d5b35136ac8747b8681d4701))
* **ci:** mutation gercek skor + coverage dot notation ([af51541](https://github.com/kayi61/super_otonom_v7/commit/af51541b70880edff7c3c8160c95ec63dadcd418))
* **ci:** mutation iptal ve yavaslik — hedef pytest, cancel kapali ([b0b4713](https://github.com/kayi61/super_otonom_v7/commit/b0b4713698c7cbdedf4fea4659d1b5bd08fa9be8))
* **ci:** mutmut 2.x pin — workflow'da explicit versiyon, lint fix ([52fdb56](https://github.com/kayi61/super_otonom_v7/commit/52fdb562c9028e4883fdf08a82e3d4ef2d064bb9))
* **ci:** mutmut runner seri pytest — xdist -n 2 kaldirildi ([8200de9](https://github.com/kayi61/super_otonom_v7/commit/8200de97e075a9c40036281660287fa618b6e69c))
* **ci:** mutmut_gate result-ids boslukla ayrilmis ID sayimi ([646bce3](https://github.com/kayi61/super_otonom_v7/commit/646bce3d7ab3d9aecb29f87a726ae0b221238529))
* **ci:** omit ops-only modules from coverage denominator. ([95aae1d](https://github.com/kayi61/super_otonom_v7/commit/95aae1d50b913129989f45c2df1e1ea7b803440a))
* **ci:** persist-credentials false + disable go cache on all checkout steps ([7f245e0](https://github.com/kayi61/super_otonom_v7/commit/7f245e07843f0ff4b6bbd9f38e7db86c8b724e19))
* **ci:** pytest-full — state load, wfa log, atomic_write shim ([070fb43](https://github.com/kayi61/super_otonom_v7/commit/070fb4363c749afd69e69bb10e6a79d3de8c5614))
* **ci:** run coverage matrix without pytest-xdist. ([ec64bc1](https://github.com/kayi61/super_otonom_v7/commit/ec64bc166edae675bcb78894a8cf081fb19c67cb))
* **ci:** testnet_ci markers and OrderEngine mock on bot_engine ([a978cac](https://github.com/kayi61/super_otonom_v7/commit/a978cac328b226c2c89afddb3c237a366e3931af))
* Dockerfile Python version, phase 46-55 tests, bare except audit ([9a1ab8e](https://github.com/kayi61/super_otonom_v7/commit/9a1ab8e7cf524e2f3e4a9948766614a6aa9c788c))
* Dockerfile, phase 46-55 tests, bare except audit — 3 acil düzeltme ([2aea10f](https://github.com/kayi61/super_otonom_v7/commit/2aea10f7f5ee9b23cabc7273acd2a198f5a354f3))
* **docker:** torch 2.9.0+cpu for Python 3.14 slim base image ([50df04c](https://github.com/kayi61/super_otonom_v7/commit/50df04c7c5dafc879ca566e7cc9b37d78bba9385))
* event_ts race condition - derivatives_intel and smart_money_tracker ([4844d7a](https://github.com/kayi61/super_otonom_v7/commit/4844d7a1bbe20c027688aabc5aa3dd60037b2f1e))
* Faz A acil düzeltmeler — 4 kritik sorun ([c5005e0](https://github.com/kayi61/super_otonom_v7/commit/c5005e0d9295c94e06fdcd54e2dae2cc746f3635))
* Faz A acil düzeltmeler — test fix, tracker, exports, stub ([dea5b5b](https://github.com/kayi61/super_otonom_v7/commit/dea5b5be56cb036b92dc1ed93ab89f45615d6208))
* multi-symbol edge_evidence interpretation hold_frac bug ([23fb5ee](https://github.com/kayi61/super_otonom_v7/commit/23fb5ee3eaa11c7ed208d2031a12e65528850de4))
* nightly-kupiec backtest failure artik workflow'u FAIL yapiyor ([c70c9d2](https://github.com/kayi61/super_otonom_v7/commit/c70c9d289eee8c50f2a7afbba341a199e8990a81))
* nightly-kupiec backtest failure workflow'u FAIL yapiyor ([05361e4](https://github.com/kayi61/super_otonom_v7/commit/05361e47a11de9011d4d97534fb8ff1d071a4367))
* prometheus gauge duplikasyon hatası düzeltildi ([cbdfb07](https://github.com/kayi61/super_otonom_v7/commit/cbdfb0718e776558aa524ed4bc13a86812b5aaff))
* **PROMPT-03:** skip empty checksums.sha256 on restore verify ([5dc0684](https://github.com/kayi61/super_otonom_v7/commit/5dc0684f508e1304e1aa03cd7fec229a04140ad5))
* pytest-full — hard_safety patches and CB_OPEN log level ([a57de57](https://github.com/kayi61/super_otonom_v7/commit/a57de57c88f32a48cca46514caa7449334c2cd1e))
* register execution/ in package topology allowed subpackages ([8bc96c1](https://github.com/kayi61/super_otonom_v7/commit/8bc96c1be2de37d5d7055866ff957600418c64c8))
* release gate smoke import path duzelt (test dosyasi tasindi) ([55530fc](https://github.com/kayi61/super_otonom_v7/commit/55530fc6572086c4ea4c1832f0e41115909d4532))
* **release-please:** run only on main push ([6253807](https://github.com/kayi61/super_otonom_v7/commit/62538075a27ffadcdb20ccbfc33648606e13be08))
* remove unused pytest imports in phase_48/51/52 tests (ruff F401) ([1538cb9](https://github.com/kayi61/super_otonom_v7/commit/1538cb9591523e5aee0b185e2985339acc8e58cf))
* ruff ci-quick — import order and unused vars ([8951b1e](https://github.com/kayi61/super_otonom_v7/commit/8951b1e4da8b450e233924001124058e5f207560))
* ruff hataları düzeltildi - import sıralama ve kullanılmayan değişkenler ([d9a3675](https://github.com/kayi61/super_otonom_v7/commit/d9a3675412e2d956318f7796bd1f357bc9d173c9))
* ruff import cleanup for ci-quick ([2dbc792](https://github.com/kayi61/super_otonom_v7/commit/2dbc7929ab2df05b883755925887c4dff48b06f3))
* ruff import order in new coverage tests ([1249164](https://github.com/kayi61/super_otonom_v7/commit/124916430c5bc642a16b73b5f7bef8edb3e0a2d8))
* ruff import order in test_audit_modules_coverage ([f9c3d00](https://github.com/kayi61/super_otonom_v7/commit/f9c3d003b91e62afd65601da8b2eb32f4a6f77d6))
* ruff per-file-ignores path guncelle (super_otonom/ -&gt; tests/) ([a6872c8](https://github.com/kayi61/super_otonom_v7/commit/a6872c8d788a98c4c0556616a3d1dbbd482d3223))
* setuptools build backend düzelt ([141e59f](https://github.com/kayi61/super_otonom_v7/commit/141e59f754da30a59dcc91e264bad83fc442a783))
* test_ai_layer Python 3.10 uyumu ([afafd33](https://github.com/kayi61/super_otonom_v7/commit/afafd3324bd06d060ef77cfe752c6449705e2724))
* **test:** CB uyari testinde throttle ve caplog flakiness ([5284118](https://github.com/kayi61/super_otonom_v7/commit/5284118b6affdfea2ef48b5d5b60c67137b927e0))
* **test:** docker compose config on CI without .env file ([bfd24d7](https://github.com/kayi61/super_otonom_v7/commit/bfd24d7885daff7acd07d7a5e06a6f44889bf374))
* **test:** make stale assertion independent of EXCHANGE_TIMEFRAME in CI. ([7791a76](https://github.com/kayi61/super_otonom_v7/commit/7791a76b896b234d99a57024963eac260b8ba81f))
* **test:** portfolio risk CVaR threshold — VR-04 Student-t ES is larger ([ace78ba](https://github.com/kayi61/super_otonom_v7/commit/ace78ba78bd48b8a7d7048fd5348776c00f51809))
* **tests:** update layout fastrun assertions for zero in-package state ([4120204](https://github.com/kayi61/super_otonom_v7/commit/4120204e60d80723e54d71fee43be23121f16f93))
* **tests:** use async def + pytest.mark.asyncio for entry test ([3a63ac4](https://github.com/kayi61/super_otonom_v7/commit/3a63ac45d2b24fbc9501993681a5710c131ee55c))
* **test:** vol spike float boundary — CI uyumlu assert ([254a37e](https://github.com/kayi61/super_otonom_v7/commit/254a37e57034afc899914996aa41599832efdf18))
* tüm prometheus metrik duplikasyonları düzeltildi ([b0bc682](https://github.com/kayi61/super_otonom_v7/commit/b0bc682bcfe48424e6c95ede0788ae2d00a75f39))
* update bot_engine topology manifest (916/1283 lines after log.warning) ([340f1b7](https://github.com/kayi61/super_otonom_v7/commit/340f1b7818dcca33110e58dc9d584d85ac0f61a0))
* update bot_engine_topology manifest for new line counts ([ae540b4](https://github.com/kayi61/super_otonom_v7/commit/ae540b4a5aa0670b612cae2b3711c349d06a4aa7))
* update coverage omit paths for moved infra/ modules ([bfa98db](https://github.com/kayi61/super_otonom_v7/commit/bfa98db6cc237507cc309c3f0bcab9f55111ddea))
* update tests to use specific exception types matching narrowed handlers ([19cc8a9](https://github.com/kayi61/super_otonom_v7/commit/19cc8a94075a5fd34cd9cd62814ae09ca8ee0078))
* **vr-01:** CI ruff, portfolio RiskEngine entegrasyonu, golden fixture ([9d51c5c](https://github.com/kayi61/super_otonom_v7/commit/9d51c5c2fc4470f463321c1342dbafd97b819c7e))
* **vr-01:** package topology test + mutmut 2.x pin ([96a8d4f](https://github.com/kayi61/super_otonom_v7/commit/96a8d4f4fa48f5cfee701b0a395e3403f1b0c6f1))
* **windows:** UTF-8 stdout for deploy_env_check + PYTHONUTF8 in CI Windows ([202846b](https://github.com/kayi61/super_otonom_v7/commit/202846bb217ab00e11478b994f395a7de7e79046))

## v7.0.0 (2026-04-25) — Sürüm tekilleştirme

- **`__version__` tek kaynak:** `super_otonom/__init__.py` → `"7.0.0"`.
- **`GENERAL["version"]`:** aynı değer `from . import __version__` ile bağlandı; drift riski giderildi.
- **`pyproject.toml` / `[project] version`:** `7.0.0` ile hizalı (paket yayımlama).
- **`main_loop`:** log satırındaki yedek sürüm `__version__` ile uyumlu.

### Kurumsal Risk Yol Haritası (VR-01 → VR-27)
- VR-01 Unified RiskEngine
- VR-02 VaR modelleri (Hist/Param/MC)
- VR-03 Cornish-Fisher VaR genişlemesi
- VR-04 CVaR / Expected Shortfall
- VR-05 RiskConfig Basel uyumu
- VR-06 EVT (POT Peaks Over Threshold)
- VR-07 FHS (GARCH(1,1) Filtreli Tarihsel Sim)
- VR-08 LVaR (BDSS + Time-To-Liquidate)
- VR-09 VaR ayrıştırma (Component/Marginal/Incremental)
- VR-10 Regime-Conditional VaR (koşullu VaR)
- VR-11 Stressed VaR (Basel 2.5 rescaling)
- VR-12 Stress Senaryo Kütüphanesi + Reverse Stress
- VR-13 Kupiec POF backtest
- VR-14 Christoffersen Independence + Conditional Coverage
- VR-15 Basel Traffic Light backtest
- VR-16 P&L Attribution + Unexplained PnL Drift
- VR-17 Pre-trade Marginal VaR gate
- VR-18 VaR-aware Position Sizing (Kelly + VaR Cap)
- VR-19 Kill-switch (VaR/CVaR breach tetikleyici)
- VR-20 VaR Limit Hierarchy (Strategy/Portfolio/Firm)
- VR-21 Prometheus VaR/CVaR/Stressed suite
- VR-22 Günlük Risk Raporu (otomatik üretim)
- VR-23 Grafana Risk Dashboard
- VR-24 Model Envanteri + Validasyon yönetişimi
- VR-25 Risk Appetite + Escalation Matrisi
- VR-26 Property-based VaR/CVaR invariants (Hypothesis)
- VR-27 Regime Detection Engine (statistical)

### Faz A → Faz D (Entegrasyon)
- Faz A: Acil düzeltmeler + tracker/exports/polish stub’lar
- Faz B: BotEngine ↔ RiskEngine tam entegrasyon (risk wiring)
- Faz C: Basel 10-day VaR + CI workflows + model governance
- Faz D: Polish & dokümantasyon iyileştirmeleri

---

## v6.1.0 (2026-04-24) — Hata Düzeltmeleri + Eksik Tamamlama

### Düzeltilen Hatalar

#### main_loop.py ← TAM YENİDEN YAZILDI
- **[DÜZELTME]** `analyze()` yerine `analyze_v5_1()` kullanılıyor — 4H çoklu zaman dilimi filtresi artık aktif
- **[DÜZELTME]** `calculate_with_slippage()` yerine `validate_and_calculate()` kullanılıyor — 3 katmanlı güvenlik filtresi (zaman senkronizasyonu + imbalance + fractional Kelly) artık aktif
- **[DÜZELTME]** v6 tick çıktıları (`sentiment_status`, `corr_multiplier`) artık loglanıyor
- **[DÜZELTME]** `corr_tracked_symbols` durum özetine eklendi
- **[İYİLEŞTİRME]** 4H veri çekimi paralel yapıldı (ayrı `fetch_all_ohlcv` çağrısı)
- **[İYİLEŞTİRME]** MTF log satırı `high_tf_trend` ve `mtf_filtered` bilgisini içeriyor

#### exchange_async.py
- **[EKSİK]** `get_order_status(order_id, symbol)` metodu eklendi — `OrderTracker` tarafından kullanılıyor
- **[EKSİK]** `cancel_order(order_id, symbol)` metodu eklendi — `OrderTracker` tarafından kullanılıyor

#### risk_manager.py
- **[HATA]** `log.critical()` ve `log.debug()` içindeki `%%%.2f` format string hatası düzeltildi → `%%.2f%%`

#### bot_engine.py
- **[HATA]** `_open_exposure()`: `pos["entry"]` ve `pos["qty"]` sözlük erişimi `.get()` ile koruma altına alındı — `KeyError` önlendi

#### config.py
- **[DÜZELTME]** `version` değeri `4.0.0` → `6.1.0` olarak güncellendi

#### ai_layer.py
- **[DÜZELTME]** Docstring sürümü `v5` → `v6.1` olarak güncellendi

### Yeni Dosyalar
- `super_otonom/__init__.py` — `__version__ = "6.1.0"` tanımı
- `requirements.txt` — Bağımlılık listesi
- `README.md` — Kurulum ve kullanım kılavuzu

---

## v6.0.0 (2026-04-24) — Korelasyon + Sentiment Katmanı

### Yeni Dosyalar
- `correlation_manager.py` — Portföy korelasyon risk yöneticisi
- `sentiment_layer.py` — Fear & Greed / haber duyarlılığı filtresi

### Değişen Dosyalar
- `bot_engine.py` — Sentiment veto + korelasyon çarpanı + tick akışı güncellemesi

---

## v5.1.0 (2026-04-24)
- `position_sizer.py`: `validate_and_calculate()` — 3 katmanlı güvenlik filtresi
- `risk_manager.py`: `check_dynamic_risk()` — volatiliteye duyarlı günlük limit
- `analyzer.py`: `analyze_v5_1()` — 4H trend uyum kontrolü

## v5.0.0 (2026-04-23)
- Hurst exponent rejim tespiti
- CircuitBreaker (exchange hata yönetimi)
- Prometheus: slippage, regime, circuit_breaker metrikleri
- AI karar gerekçesi: `get_decision_reason()`, `validate_signal()` üçlüsü
