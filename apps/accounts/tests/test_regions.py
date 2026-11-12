"""전국 행정동 데이터 · 동네 3단 선택(폼/위젯/HTMX 옵션) · 목록 동네 필터."""

import importlib
from types import SimpleNamespace

from django.apps import apps as global_apps
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from apps.accounts import regions
from apps.accounts.forms import ProfileForm, RegionChoiceField, SignUpForm
from apps.accounts.models import Profile, Region
from apps.products.models import Product

from .factories import make_product, make_user

load_migration = importlib.import_module("apps.accounts.migrations.0004_load_hangjeongdong")


def region(sido, sigungu, dong):
    return Region.objects.get(sido=sido, sigungu=sigungu, dong=dong)


class HangjeongdongDataTests(TestCase):
    """마이그레이션(0004)이 넣은 데이터."""

    def test_full_list_loaded_with_codes(self):
        self.assertEqual(Region.objects.count(), 3559)
        self.assertEqual(Region.objects.filter(code__isnull=True).count(), 0)
        self.assertEqual(len(load_migration.read_rows()), 3559)

    def test_toegye_dong_under_gangwon_chuncheon(self):
        toegye = region("강원특별자치도", "춘천시", "퇴계동")
        self.assertEqual(toegye.code, "5111066000")
        self.assertEqual(toegye.name, "강원특별자치도 춘천시 퇴계동")
        self.assertEqual(toegye.short_name, "퇴계동")

    def test_legacy_seed_names_replaced(self):
        # 0002 시드의 비공식 이름은 (아무도 안 쓰니) 지워지고 공식 이름만 남아요
        self.assertFalse(Region.objects.filter(dong="성수동1가").exists())
        self.assertFalse(Region.objects.filter(sigungu="부천시").exists())
        self.assertFalse(Region.objects.filter(sigungu="수원시 장안구", dong="정자동").exists())
        self.assertTrue(Region.objects.filter(sigungu="수원시 장안구", dong="정자1동").exists())
        # 분당구 정자동은 실제 행정동이라 그대로 있어요
        self.assertTrue(Region.objects.filter(sigungu="성남시 분당구", dong="정자동").exists())

    def test_sido_list_and_sejong(self):
        sidos = regions.sido_choices()
        self.assertEqual(len(sidos), 16)
        self.assertIn("전남광주통합특별시", sidos)
        self.assertEqual(sidos, sorted(sidos))  # 가나다순
        self.assertEqual(regions.sigungu_choices("세종특별자치시"), ["세종시"])

    def test_sigungu_lookup_is_scoped_by_sido(self):
        busan = regions.sigungu_choices("부산광역시")
        daegu = regions.sigungu_choices("대구광역시")
        self.assertIn("동구", busan)
        self.assertIn("동구", daegu)
        self.assertNotIn("춘천시", busan)
        busan_dong = [name for _, name in regions.dong_choices("부산광역시", "동구")]
        daegu_dong = [name for _, name in regions.dong_choices("대구광역시", "동구")]
        self.assertIn("초량1동", busan_dong)
        self.assertNotIn("신암1동", busan_dong)
        self.assertIn("신암1동", daegu_dong)
        self.assertNotIn("초량1동", daegu_dong)
        self.assertEqual(regions.sigungu_choices(""), [])
        self.assertEqual(regions.dong_choices("부산광역시", ""), [])

    def test_natural_sort(self):
        names = [name for _, name in regions.dong_choices("서울특별시", "노원구")]
        self.assertLess(names.index("상계9동"), names.index("상계10동"))
        self.assertLess(names.index("상계2동"), names.index("상계3·4동"))
        self.assertEqual(regions.korean_sort_key("상계10동"), ["상계", 10, "동"])


class LoadMigrationLegacyTests(TestCase):
    """운영 DB 처럼 0002 시드가 이미 있는 상태에서 0004 를 다시 돌려 본다."""

    def run_load(self):
        load_migration.load_regions(global_apps, SimpleNamespace(connection=connection))

    def test_upsert_and_legacy_cleanup(self):
        # 예전 시드 행 3개: 프로필이 쓰는 것 · 상품이 쓰는 것 · 아무도 안 쓰는 것
        by_profile = Region.objects.create(sido="경기도", sigungu="부천시", dong="중동")
        by_product = Region.objects.create(sido="서울특별시", sigungu="성동구", dong="성수동1가")
        unused = Region.objects.create(sido="서울특별시", sigungu="강남구", dong="역삼동")
        user = make_user(region=by_profile)
        product = make_product(user, region=by_product)
        # 코드가 비어 있는 공식 행(→ 채워짐) · 빠진 공식 행(→ 다시 생김)
        toegye = region("강원특별자치도", "춘천시", "퇴계동")
        Region.objects.filter(pk=toegye.pk).update(code=None)
        Region.objects.filter(code="1144066000").delete()  # 마포구 서교동

        self.run_load()

        self.assertTrue(Region.objects.filter(pk=by_profile.pk, code__isnull=True).exists())
        self.assertTrue(Region.objects.filter(pk=by_product.pk, code__isnull=True).exists())
        self.assertFalse(Region.objects.filter(pk=unused.pk).exists())
        self.assertEqual(Profile.objects.get(user=user).region_id, by_profile.pk)
        self.assertEqual(Product.objects.get(pk=product.pk).region_id, by_product.pk)
        toegye.refresh_from_db()
        self.assertEqual(toegye.code, "5111066000")
        self.assertEqual(region("서울특별시", "마포구", "서교동").code, "1144066000")
        self.assertEqual(Region.objects.filter(code__isnull=False).count(), 3559)
        self.assertEqual(Region.objects.count(), 3561)

        # 다시 돌려도 그대로 (멱등)
        self.run_load()
        self.assertEqual(Region.objects.count(), 3561)

    def test_related_objects_found_with_historical_models(self):
        """migrate 가 넘기는 역사적(historical) 앱 상태에서도 Region 을 가리키는 FK 를 찾아요."""
        from django.db.migrations.executor import MigrationExecutor

        state_apps = MigrationExecutor(connection).loader.project_state(("accounts", "0004_load_hangjeongdong")).apps
        HistRegion = state_apps.get_model("accounts", "Region")
        self.assertIsNot(HistRegion, Region)
        kept = Region.objects.create(sido="경기도", sigungu="부천시", dong="중동")
        unused = Region.objects.create(sido="서울특별시", sigungu="강남구", dong="역삼동")
        make_user(region=kept)
        load_migration.load_regions(state_apps, SimpleNamespace(connection=connection))
        self.assertTrue(Region.objects.filter(pk=kept.pk).exists())
        self.assertFalse(Region.objects.filter(pk=unused.pk).exists())

    def test_legacy_rows_hidden_from_new_selection_but_kept_for_current(self):
        legacy = Region.objects.create(sido="경기도", sigungu="부천시", dong="중동")
        self.assertNotIn("부천시", regions.sigungu_choices("경기도"))
        self.assertIn("부천시", regions.sigungu_choices("경기도", current=legacy))
        self.assertEqual(regions.dong_choices("경기도", "부천시"), [])
        self.assertEqual(regions.dong_choices("경기도", "부천시", current=legacy), [(legacy.pk, "중동")])


class RegionOptionsEndpointTests(TestCase):
    url = reverse("accounts:region_options")

    def test_sigungu_options_for_sido(self):
        res = self.client.get(self.url, {"level": "sigungu", "sido": "강원특별자치도"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '<option value="">시/군/구 선택</option>', html=True)
        self.assertContains(res, '<option value="춘천시">춘천시</option>', html=True)
        self.assertNotContains(res, "수원시")
        self.assertIn("max-age=3600", res["Cache-Control"])

    def test_dong_options_scoped_by_sido_and_sigungu(self):
        toegye = region("강원특별자치도", "춘천시", "퇴계동")
        res = self.client.get(self.url, {"level": "dong", "sido": "강원특별자치도", "sigungu": "춘천시"})
        self.assertContains(res, f'<option value="{toegye.pk}">퇴계동</option>', html=True)
        self.assertContains(res, '<option value="">읍/면/동 선택</option>', html=True)
        res = self.client.get(self.url, {"level": "dong", "sido": "부산광역시", "sigungu": "동구"})
        self.assertContains(res, "초량1동")
        self.assertNotContains(res, "신암1동")

    def test_accepts_widget_prefixed_names(self):
        # 위젯 select 이름(region_sido, region_sigungu) 그대로 보내도 돼요 (HTMX 가 그렇게 보냄)
        res = self.client.get(
            self.url, {"level": "dong", "region_sido": "강원특별자치도", "region_sigungu": "춘천시"}
        )
        self.assertContains(res, "퇴계동")

    def test_empty_or_unknown_parent_returns_only_placeholder(self):
        res = self.client.get(self.url, {"level": "sigungu", "sido": ""})
        self.assertEqual(res.content.decode().count("<option"), 1)
        res = self.client.get(self.url, {"level": "dong", "sido": "없는도", "sigungu": "춘천시"})
        self.assertEqual(res.content.decode().count("<option"), 1)

    def test_bad_level_and_method(self):
        self.assertEqual(self.client.get(self.url, {"level": "zzz"}).status_code, 400)
        self.assertEqual(self.client.post(self.url, {"level": "sigungu"}).status_code, 405)

    def test_crafted_params_return_placeholder_only(self):
        for bad in ("\x00", "강원특별자치도\x00", "x" * 1000, "<script>alert(1)</script>", "'\"", "²"):
            for level in ("sigungu", "dong"):
                with self.subTest(value=bad[:10], level=level):
                    res = self.client.get(self.url, {"level": level, "sido": bad, "sigungu": bad})
                    self.assertEqual(res.status_code, 200)
                    self.assertEqual(res.content.decode().count("<option"), 1)
                    self.assertNotContains(res, "<script>")
        self.assertEqual(regions.clean_param("강원\x00"), "")
        self.assertEqual(regions.clean_param("  " + "가" * 30), "가" * 20)
        self.assertEqual(regions.clean_param(None), "")

    def test_single_query(self):
        with self.assertNumQueries(1):
            self.client.get(self.url, {"level": "dong", "sido": "강원특별자치도", "sigungu": "춘천시"})


class RegionFieldTests(TestCase):
    def setUp(self):
        self.toegye = region("강원특별자치도", "춘천시", "퇴계동")

    def bind(self, **data):
        form = SignUpForm(
            data={
                "username": "newbie_02",
                "nickname": "새 이웃",
                "name": "홍길동",
                "birth_date": "2000-01-15",
                "phone": "01012345679",
                "password1": "Poly-market-2026!",
                "password2": "Poly-market-2026!",
                **data,
            }
        )
        form.is_valid()
        return form

    def test_full_cascade_is_valid(self):
        form = self.bind(region_sido="강원특별자치도", region_sigungu="춘천시", region=str(self.toegye.pk))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["region"], self.toegye)
        self.assertEqual(form.cleaned_data["nickname"], "새 이웃")  # 닉네임 띄어쓰기 허용 유지

    def test_required_messages_are_korean(self):
        self.assertEqual(self.bind().errors["region"], ["동네를 선택해 주세요."])
        partial = self.bind(region_sido="강원특별자치도", region_sigungu="춘천시", region="")
        self.assertEqual(partial.errors["region"], ["읍/면/동까지 선택해 주세요."])
        self.assertEqual(self.bind(region="999999").errors["region"], ["목록에서 동네를 골라 주세요."])

    def test_rerender_after_error_keeps_partial_selection(self):
        form = self.bind(region_sido="강원특별자치도", region_sigungu="춘천시", region="")
        html = str(form["region"])
        self.assertInHTML('<option value="강원특별자치도" selected>강원특별자치도</option>', html)
        self.assertInHTML('<option value="춘천시" selected>춘천시</option>', html)
        # 읍/면/동 옵션까지 서버가 미리 그려 둬서 추가 요청 없이 고를 수 있어요
        self.assertInHTML(f'<option value="{self.toegye.pk}">퇴계동</option>', html)
        self.assertIn('aria-invalid="true"', html)

    def test_widget_renders_three_labelled_selects(self):
        html = str(SignUpForm()["region"])
        for level_id, label in (("id_region_sido", "시/도"), ("id_region_sigungu", "시/군/구"), ("id_region", "읍/면/동")):
            self.assertIn(f'id="{level_id}"', html)
            self.assertInHTML(f'<label for="{level_id}" class="sr-only">{label}</label>', html)
        self.assertIn(reverse("accounts:region_options"), html)
        self.assertIn('hx-include="#id_region_sido"', html)
        self.assertIn("disabled", html)

    def test_initial_value_renders_selected_path(self):
        me = make_user(region=self.toegye)
        html = str(ProfileForm(instance=me.profile)["region"])
        self.assertInHTML('<option value="강원특별자치도" selected>강원특별자치도</option>', html)
        self.assertInHTML('<option value="춘천시" selected>춘천시</option>', html)
        self.assertInHTML(f'<option value="{self.toegye.pk}" selected>퇴계동</option>', html)
        self.assertInHTML('<option value="효자1동">효자1동</option>', html, count=0)  # 값은 pk
        self.assertNotIn("disabled", html)

    def test_legacy_initial_value_is_kept_selectable(self):
        legacy = Region.objects.create(sido="경기도", sigungu="부천시", dong="중동")
        me = make_user(region=legacy)
        html = str(ProfileForm(instance=me.profile)["region"])
        self.assertInHTML('<option value="부천시" selected>부천시</option>', html)
        self.assertInHTML(f'<option value="{legacy.pk}" selected>중동</option>', html)
        # 바꾸지 않고 저장해도 그대로 통과 (ProfileForm 이 지금 값만 허락)
        form = ProfileForm(
            instance=me.profile,
            data={"nickname": me.profile.nickname, "bio": "", "region_sido": "경기도",
                  "region_sigungu": "부천시", "region": str(legacy.pk)},
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["region"], legacy)

    def test_legacy_pk_rejected_when_not_current_value(self):
        legacy = Region.objects.create(sido="경기도", sigungu="부천시", dong="중동")
        # 새 가입에는 예전 시드 행을 고를 수 없어요
        self.assertEqual(self.bind(region=str(legacy.pk)).errors["region"], ["목록에서 동네를 골라 주세요."])
        # 다른 사람 프로필: 내 동네가 아니면 안 돼요
        me = make_user(region=self.toegye)
        form = ProfileForm(instance=me.profile, data={"nickname": me.profile.nickname, "bio": "", "region": str(legacy.pk)})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["region"], ["목록에서 동네를 골라 주세요."])
        # 필드 기본값도 코드 있는 행만
        with self.assertRaises(Exception):
            RegionChoiceField().clean(str(legacy.pk))

    def test_pk_must_match_submitted_upper_levels(self):
        gangneung = region("강원특별자치도", "강릉시", "강남동")
        form = self.bind(region_sido="서울특별시", region_sigungu="마포구", region=str(gangneung.pk))
        self.assertEqual(form.errors["region"], ["고른 시/도·시/군/구와 읍/면/동이 맞지 않아요. 다시 골라 주세요."])
        # 다시 그릴 땐 고른 위 단계를 보여주고 읍/면/동은 비워 둬요
        html = str(form["region"])
        self.assertInHTML('<option value="마포구" selected>마포구</option>', html)
        self.assertNotIn(f'value="{gangneung.pk}" selected', html)
        # 같은 시/도의 다른 시/군/구도 거절
        form = self.bind(region_sido="강원특별자치도", region_sigungu="춘천시", region=str(gangneung.pk))
        self.assertIn("region", form.errors)
        # 위 단계를 안 보내면(예전 클라이언트) pk 만으로 통과
        self.assertTrue(self.bind(region=str(gangneung.pk)).is_valid())

    def test_crafted_pk_values_do_not_crash(self):
        for bad in ("²", "١٢", "-1", "1.0", " 1 OR 1=1", "9" * 40, "\x00"):
            with self.subTest(value=bad):
                form = self.bind(region_sido="서울특별시", region_sigungu="마포구", region=bad)
                self.assertIn("region", form.errors)
                str(form["region"])  # 다시 그려도 에러 없이
        self.assertIsNone(regions.region_by_pk("²"))
        self.assertIsNone(regions.parse_pk("-1"))
        self.assertEqual(regions.parse_pk(" 12 "), 12)


class RegionPagesTests(TestCase):
    """가입 · 프로필 수정 · 상품 등록/수정 화면에서 3단 선택."""

    def setUp(self):
        self.toegye = region("강원특별자치도", "춘천시", "퇴계동")

    def test_signup_with_cascade(self):
        res = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "chuncheon",
                "nickname": "춘천 이웃",
                "name": "김춘천",
                "birth_date": "1995-05-05",
                "phone": "01055556666",
                "region_sido": "강원특별자치도",
                "region_sigungu": "춘천시",
                "region": str(self.toegye.pk),
                "password1": "Poly-market-2026!",
                "password2": "Poly-market-2026!",
            },
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(Profile.objects.get(user__username="chuncheon").region, self.toegye)

    def test_signup_error_rerender_keeps_selection(self):
        res = self.client.post(
            reverse("accounts:signup"), {"region_sido": "강원특별자치도", "region_sigungu": "춘천시", "region": ""}
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "읍/면/동까지 선택해 주세요.")
        self.assertContains(res, '<option value="춘천시" selected>춘천시</option>', html=True)

    def test_signup_post_with_crafted_region_returns_form_error(self):
        for bad in ("²", "\x00", "x" * 1000):
            with self.subTest(value=bad[:5]):
                res = self.client.post(
                    reverse("accounts:signup"),
                    {"region_sido": "서울특별시\x00", "region_sigungu": "마포구" * 50, "region": bad},
                )
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, "목록에서 동네를 골라 주세요.")

    def test_product_keeps_legacy_region_only_as_current_value(self):
        legacy = Region.objects.create(sido="경기도", sigungu="부천시", dong="중동")
        other_legacy = Region.objects.create(sido="서울특별시", sigungu="성동구", dong="성수동1가")
        me = make_user(region=legacy)
        self.client.force_login(me)
        res = self.client.get(reverse("products:create"))
        self.assertContains(res, f'<option value="{legacy.pk}" selected>중동</option>', html=True)
        data = {"title": "자전거 팔아요", "category": make_product(me).category_id, "condition": "GOOD",
                "price": 1000, "content": "잘 나가요 상태 좋아요"}
        from apps.products.forms import ProductForm

        # 내 동네(예전 행) → 통과, 남의 예전 행 → 거절
        form = ProductForm(data={**data, "region": str(legacy.pk)}, user=me)
        form.is_valid()
        self.assertNotIn("region", form.errors)
        form = ProductForm(data={**data, "region": str(other_legacy.pk)}, user=me)
        form.is_valid()
        self.assertEqual(form.errors["region"], ["목록에서 동네를 골라 주세요."])
        # 원래 예전 행에 올린 상품은 수정할 때 그대로 둘 수 있어요
        product = make_product(me, region=other_legacy)
        form = ProductForm(data={**data, "region": str(other_legacy.pk)}, instance=product, user=me)
        form.is_valid()
        self.assertNotIn("region", form.errors)

    def test_profile_edit_preselected(self):
        me = make_user(region=self.toegye)
        self.client.force_login(me)
        res = self.client.get(reverse("accounts:profile_edit"))
        self.assertContains(res, f'<option value="{self.toegye.pk}" selected>퇴계동</option>', html=True)
        self.assertContains(res, "<legend", html=False)

    def test_product_create_defaults_and_edit_preselected(self):
        me = make_user(region=self.toegye)
        self.client.force_login(me)
        res = self.client.get(reverse("products:create"))
        self.assertContains(res, f'<option value="{self.toegye.pk}" selected>퇴계동</option>', html=True)
        other = region("서울특별시", "마포구", "합정동")
        product = make_product(me, region=other)
        res = self.client.get(reverse("products:update", args=[product.pk]))
        self.assertContains(res, '<option value="마포구" selected>마포구</option>', html=True)
        self.assertContains(res, f'<option value="{other.pk}" selected>합정동</option>', html=True)
        # 동까지 안 고르고 저장하면 한국어 에러 + 고른 단계 유지
        res = self.client.post(
            reverse("products:update", args=[product.pk]),
            {"title": "자전거 팔아요", "category": product.category_id, "condition": product.condition,
             "price": 1000, "content": "잘 나가요 상태 좋아요", "region_sido": "강원특별자치도",
             "region_sigungu": "춘천시", "region": ""},
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "읍/면/동까지 선택해 주세요.")
        self.assertContains(res, '<option value="춘천시" selected>춘천시</option>', html=True)
        product.refresh_from_db()
        self.assertEqual(product.region, other)


class ProductRegionFilterTests(TestCase):
    """목록 필터: 시/도 · 시/군/구 · 읍/면/동 어느 단계에서든."""

    @classmethod
    def setUpTestData(cls):
        cls.toegye = region("강원특별자치도", "춘천시", "퇴계동")
        cls.hyoja = region("강원특별자치도", "춘천시", "효자1동")
        cls.dangu = region("강원특별자치도", "원주시", "단구동")
        cls.seogyo = region("서울특별시", "마포구", "서교동")
        cls.seller = make_user(region=cls.seogyo)
        cls.products = {
            key: make_product(cls.seller, region=r, title=f"{key} 상품")
            for key, r in (("toegye", cls.toegye), ("hyoja", cls.hyoja), ("dangu", cls.dangu), ("seogyo", cls.seogyo))
        }

    def titles(self, params, user=None):
        if user:
            self.client.force_login(user)
        res = self.client.get(reverse("products:list"), params)
        self.assertEqual(res.status_code, 200)
        return res, {p.title.split()[0] for p in res.context["products"]}

    def test_sido_level(self):
        res, titles = self.titles({"sido": "강원특별자치도", "sigungu": "", "region": ""})
        self.assertEqual(titles, {"toegye", "hyoja", "dangu"})
        self.assertEqual(res.context["region_value"], "sido")
        self.assertContains(res, "강원특별자치도 전체")

    def test_sigungu_level(self):
        res, titles = self.titles({"sido": "강원특별자치도", "sigungu": "춘천시"})
        self.assertEqual(titles, {"toegye", "hyoja"})
        self.assertContains(res, "강원특별자치도 춘천시 전체")
        # 읍/면/동 옵션이 서버에서 그려져 있고 첫 옵션은 '춘천시 전체'
        self.assertContains(res, '<option value="">춘천시 전체</option>', html=True)
        self.assertContains(res, f'<option value="{self.toegye.pk}">퇴계동</option>', html=True)

    def test_dong_level(self):
        res, titles = self.titles({"sido": "강원특별자치도", "sigungu": "춘천시", "region": self.toegye.pk})
        self.assertEqual(titles, {"toegye"})
        self.assertEqual(res.context["region_value"], str(self.toegye.pk))
        self.assertContains(res, "강원특별자치도 춘천시 퇴계동")
        # 예전 형식(?region=<pk>)도 그대로
        _, titles = self.titles({"region": self.toegye.pk})
        self.assertEqual(titles, {"toegye"})

    def test_stale_lower_level_is_ignored(self):
        # 시/군/구를 바꿨는데 이전 동 값이 남아 있으면 → 시/군/구 전체
        res, titles = self.titles({"sido": "강원특별자치도", "sigungu": "원주시", "region": self.toegye.pk})
        self.assertEqual(titles, {"dangu"})
        self.assertEqual(res.context["region_value"], "sigungu")
        # 다른 시/도의 같은 이름 시/군/구는 없는 것으로 → 시/도 전체
        _, titles = self.titles({"sido": "강원특별자치도", "sigungu": "마포구"})
        self.assertEqual(titles, {"toegye", "hyoja", "dangu"})

    def test_all_regions_and_bad_values(self):
        _, titles = self.titles({"sido": ""})
        self.assertEqual(titles, set(self.products))
        res, titles = self.titles({"sido": "없는도", "sigungu": "춘천시"})
        self.assertEqual(titles, set(self.products))
        self.assertEqual(res.context["region_value"], "all")
        self.assertContains(res, "전체 지역")

    def test_my_region_default_kept(self):
        buyer = make_user(region=self.hyoja)
        res, titles = self.titles({}, user=buyer)
        self.assertEqual(titles, {"hyoja"})
        self.assertEqual(res.context["region_value"], "me")
        self.assertContains(res, "내 동네 · 효자1동")
        # 3단 select 에 내 동네가 미리 골라져 있어서 정렬 등을 바꿔 제출해도 '내 동네' 유지
        self.assertContains(res, f'<option value="{self.hyoja.pk}" selected>효자1동</option>', html=True)
        res, titles = self.titles({"sido": "강원특별자치도", "sigungu": "춘천시", "region": self.hyoja.pk, "sort": "popular"})
        self.assertEqual(res.context["region_value"], "me")
        # 시/도에서 '전체 지역'을 고르면 전체
        _, titles = self.titles({"sido": "", "sort": "latest"})
        self.assertEqual(titles, set(self.products))

    def test_filters_and_pagination_are_preserved(self):
        res, _ = self.titles({"sido": "강원특별자치도", "sigungu": "춘천시", "sort": "popular", "status": "selling"})
        self.assertEqual(res.context["sort_value"], "popular")
        # '초기화'는 동네 필터를 유지
        self.assertEqual(res.context["reset_url"], reverse("products:list") + "?sido=%EA%B0%95%EC%9B%90%ED%8A%B9%EB%B3%84%EC%9E%90%EC%B9%98%EB%8F%84&sigungu=%EC%B6%98%EC%B2%9C%EC%8B%9C")
        # HTMX 다음 페이지 요청도 같은 범위
        res = self.client.get(
            reverse("products:list"), {"sido": "강원특별자치도", "page": 1}, HTTP_HX_REQUEST="true"
        )
        self.assertTemplateUsed(res, "products/partials/product_grid.html")
        self.assertEqual(len(res.context["products"]), 3)

    def test_crafted_params_do_not_crash(self):
        cases = [
            ({"region": "²"}, "all"),
            ({"sido": "강원특별자치도", "sigungu": "춘천시", "region": "²"}, "sigungu"),
            ({"sido": "\x00"}, "all"),
            ({"sido": "강원특별자치도", "sigungu": "\x00"}, "sido"),
            ({"sido": "강원특별자치도" + "x" * 1000}, "all"),
            ({"sido": "<b>\"'"}, "all"),
        ]
        for params, expected in cases:
            with self.subTest(params=str(params)[:40]):
                res, _ = self.titles(params)
                self.assertEqual(res.context["region_value"], expected)
                self.assertNotContains(res, "<b>\"'")

    def test_region_pk_from_other_sido_falls_back_to_upper_level(self):
        res, titles = self.titles({"sido": "강원특별자치도", "sigungu": "춘천시", "region": self.seogyo.pk})
        self.assertEqual(titles, {"toegye", "hyoja"})
        self.assertEqual(res.context["region_value"], "sigungu")
        res, titles = self.titles({"sido": "서울특별시", "sigungu": "춘천시", "region": self.toegye.pk})
        self.assertEqual(titles, {"seogyo"})
        self.assertEqual(res.context["region_value"], "sido")

    def test_legacy_sigungu_filter_matches_select(self):
        """예전 시드 행(코드 없음) 시/군/구: 내 동네일 땐 select 에도 보이고, 아니면 시/도 전체로 접혀요."""
        legacy = Region.objects.create(sido="경기도", sigungu="부천시", dong="중동")
        make_product(self.seller, region=legacy, title="bucheon 상품")
        params = {"sido": "경기도", "sigungu": "부천시", "region": ""}
        # 남이 URL 로 접근: select 에 없는 시/군/구라 '경기도 전체'로 (화면과 필터가 같음)
        res, titles = self.titles(params)
        self.assertEqual(res.context["region_value"], "sido")
        self.assertContains(res, "경기도 전체")
        # 내 동네가 부천시 중동인 사용자: 부천시가 select 에 골라진 채로 보이고 필터도 부천시
        me = make_user(region=legacy)
        res, titles = self.titles(params, user=me)
        self.assertEqual(titles, {"bucheon"})
        self.assertEqual(res.context["region_value"], "sigungu")
        self.assertContains(res, '<option value="부천시" selected>부천시</option>', html=True)
        self.assertContains(res, f'<option value="{legacy.pk}">중동</option>', html=True)

    def test_filter_form_disables_history_restore(self):
        res, _ = self.titles({"sido": "강원특별자치도"})
        self.assertContains(res, 'autocomplete="off" data-products-autosubmit')
        self.assertContains(res, "data-autosubmit-pending")  # 키보드로 훑을 땐 바로 제출하지 않음

    def test_empty_area_offers_all_regions(self):
        res, titles = self.titles({"sido": "제주특별자치도"})
        self.assertEqual(titles, set())
        self.assertContains(res, "전체 지역 보기")
        self.assertContains(res, "region=all")
