package io.github.iy88.project1.trade.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.OptionalLong;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

class TradePartyFreezeQualificationTests {
    private static final long MANAGER = 1001;
    private static final long BUYER = 1002;
    private static final long SELLER = 1003;
    private static final long PRODUCT = 2001;
    private static final long TRADE_ID = 3001;
    private static final long CASE_ID = 4001;
    private static final long CONVERSATION_ID = 5001;
    private static final Instant NOW = Instant.parse("2026-11-26T03:00:00Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);

    private final TradeRepository repository = mock(TradeRepository.class);
    private final TradePorts.Product product = mock(TradePorts.Product.class);
    private final TradePorts.Accounts accounts = mock(TradePorts.Accounts.class);
    private final TradePorts.Conversation conversations = mock(TradePorts.Conversation.class);
    private final TradePorts.Cases cases = mock(TradePorts.Cases.class);
    private final TradePorts.Notifications notifications = mock(TradePorts.Notifications.class);
    private final WriteExecutor writes = mock(WriteExecutor.class);
    private final WriteTransaction transaction = mock(WriteTransaction.class);
    private TradeApplication application;
    private ExecutionContext context;

    @BeforeEach
    @SuppressWarnings({"unchecked", "rawtypes"})
    void setUp() {
        context = new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(BUYER), UUID.randomUUID(), null, 1L, "freeze-qualification-test");
        application = new TradeApplication(repository, writes, mock(TaskSchedules.class), CLOCK,
                new TradeSettings(604800, "s2-v1", 20, 100, 200), product, accounts, conversations, cases,
                notifications, JsonMapper.builder().build());
        when(accounts.qualification(BUYER))
                .thenReturn(new TradePorts.AccountQualification(BUYER, true, false));
        when(accounts.qualification(SELLER))
                .thenReturn(new TradePorts.AccountQualification(SELLER, true, false));
        when(product.read(PRODUCT)).thenReturn(Optional.of(new TradePorts.ProductState(
                PRODUCT, SELLER, 1, "public", null, "Book", "Used book", 1_000L,
                List.of("Book"), List.of())));
        when(writes.run(any(), eq("trade.request.create"), any(), any(), any())).thenAnswer(invocation -> {
            WriteExecutor.UseCase useCase = invocation.getArgument(4);
            var command = invocation.getArgument(3);
            LockPlan plan = useCase.prepare(context, command);
            Object qualification = useCase.qualify(context, command, plan);
            return useCase.write(transaction, command, qualification, plan);
        });
    }

    @Test
    void aFrozenBuyerCannotStartANewPurchase() {
        when(repository.hasActivePartyFreeze(BUYER)).thenReturn(true);

        assertFailure();

        verify(repository, never()).insertTrade(anyLong(), anyLong(), anyLong(), any(), any());
    }

    @Test
    void aFrozenSellerCannotBeTheCounterpartyOfANewPurchase() {
        when(repository.hasActivePartyFreeze(SELLER)).thenReturn(true);

        assertFailure();

        verify(repository, never()).insertTrade(anyLong(), anyLong(), anyLong(), any(), any());
    }

    @Test
    void partyFreezePredicateDelegatesToTheTradeOwnedQuery() {
        when(repository.hasActivePartyFreeze(BUYER)).thenReturn(true);

        assertThat(application.hasActivePartyFreeze(BUYER)).isTrue();
        verify(repository).hasActivePartyFreeze(BUYER);
    }

    @Test
    void caseEnforcementTakesExclusiveLocksForBothParties() {
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade()));
        when(conversations.find(TRADE_ID)).thenReturn(OptionalLong.of(CONVERSATION_ID));

        var plan = application.prepare(MANAGER, TRADE_ID, CASE_ID, false).lockPlan();

        assertThat(plan.accounts())
                .containsEntry(MANAGER, LockPlan.AccountMode.SHARED)
                .containsEntry(BUYER, LockPlan.AccountMode.EXCLUSIVE)
                .containsEntry(SELLER, LockPlan.AccountMode.EXCLUSIVE);
    }

    @Test
    void aManagerWhoIsAlsoAPartyKeepsTheStrongerExclusiveMode() {
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade()));
        when(conversations.find(TRADE_ID)).thenReturn(OptionalLong.of(CONVERSATION_ID));

        var plan = application.prepare(BUYER, TRADE_ID, CASE_ID, false).lockPlan();

        assertThat(plan.accounts()).containsEntry(BUYER, LockPlan.AccountMode.EXCLUSIVE);
    }

    @Test
    void timeoutFreezeTakesExclusiveLocksForBothParties() {
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade()));
        when(conversations.find(TRADE_ID)).thenReturn(OptionalLong.of(CONVERSATION_ID));

        var plan = application.timeoutPlan(TRADE_ID);

        assertThat(plan.accounts())
                .containsEntry(BUYER, LockPlan.AccountMode.EXCLUSIVE)
                .containsEntry(SELLER, LockPlan.AccountMode.EXCLUSIVE);
    }

    @Test
    void accountBanPlanTakesExclusiveLocksForBothPartiesOfEveryAffectedTrade() {
        when(repository.pendingTradeIdsForAccount(BUYER)).thenReturn(List.of());
        when(repository.activeTradeIdsForAccount(BUYER)).thenReturn(List.of(TRADE_ID));
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade()));
        when(conversations.find(TRADE_ID)).thenReturn(OptionalLong.of(CONVERSATION_ID));

        var plan = application.accountBanPlan(BUYER);

        assertThat(plan.accounts())
                .containsEntry(BUYER, LockPlan.AccountMode.EXCLUSIVE)
                .containsEntry(SELLER, LockPlan.AccountMode.EXCLUSIVE);
    }

    private void assertFailure() {
        assertThatThrownBy(() -> application.createPurchaseRequest(context, "key-" + UUID.randomUUID(),
                new TradeCommands.CreatePurchaseRequest(PRODUCT, null, 1)))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("TRADE_FROZEN");
                    assertThat(error.status()).isEqualTo(409);
                });
    }

    private static Trade trade() {
        return new Trade(TRADE_ID, PRODUCT, BUYER, SELLER, TradeStatus.IN_PROGRESS, null, null, 3,
                null, null, NOW, null, null, NOW, NOW);
    }
}
